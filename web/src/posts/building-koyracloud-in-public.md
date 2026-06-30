I set out to build my own Vercel. Not a toy clone for a blog post — a real platform that I and my clients could ship production apps onto, running on hardware I already owned. A month later it was deploying live apps. This is what that month actually looked like, including the design I got wrong first.

The goal was narrow on purpose: the "connect a repo and it deploys" experience of Vercel or Render, but self-hosted on a Docker Swarm, for a single trusted operator. Not multi-tenant SaaS. Not a startup. A tool. Knowing what I was *not* building turned out to be the most important decision I made.

## The shape of the problem

A platform-as-a-service is mostly plumbing you'd otherwise write by hand for every app: clone the repo, install dependencies, build it, give it HTTPS, point a domain at it, inject secrets, keep it running, let it persist data, and let you roll back when you break it. Each of those is a solved problem in isolation. The work is in wiring them into one loop that a person can drive from a dashboard without thinking about any of it.

So the architecture fell out into two halves. A **control plane** — a FastAPI + React app running as a single Swarm service, driving the cluster through a mounted Docker socket. And a **build/run pipeline** that turns a git repo into a running container. The control plane is the brain; the pipeline is the muscle.

The contract with the user is a single file committed to their repo, `.paas/app.yaml`:

```yaml
name: my-app
runtime: python+node
port: 8000
build:
  - pip install -r requirements.txt
  - bash -c "cd web && npm ci && npm run build"
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
persist: [data]
secrets: [SECRET_KEY]
healthcheck: /health
```

Or, if they'd rather, `runtime: dockerfile` and koyracloud builds their own Dockerfile as-is. That escape hatch mattered more than I expected — the moment someone has a build you didn't anticipate, "bring your own Dockerfile" is the difference between adoption and a shrug.

## The design I got wrong

The first version kept each app's code, `node_modules`, and virtualenv on a shared NFS volume. A one-off container built dependencies in place; the long-running service then served the code straight off NFS. Clean on a whiteboard. Hand-rolled a dependency-hash check so it wouldn't rebuild every time.

It worked until it didn't. NFS is built around network round-trips, and a `node_modules` tree is thousands of tiny files. Every build walked those trees and hammered the NFS server with metadata calls. And the control plane's own database lived on the same NFS. So a heavy build would starve the database of I/O, its healthcheck would time out, and the control plane would crash *mid-deploy* — taking the deployment with it. I had built a way for any app deploy to knock over the entire platform.

The fix was to flip the model. Now every deploy builds a per-app **container image** on local disk (fast, no NFS contention), pushes it to an internal `registry:2` service, and Swarm runs the app from that image. Docker's layer cache replaced my hand-rolled hashing — and I deleted that code entirely. Because any node can pull the image, apps are pinned to nothing and reschedule anywhere. NFS is now touched only for persisted data, the thing it's actually good at. The rewrite removed more code than it added, which is usually the sign you've found the right shape.

## What I deliberately left out

Every feature I said no to bought simplicity somewhere else:

- **No multi-tenant isolation of untrusted code.** It's a single-operator platform for trusted code. That one assumption deletes an enormous amount of sandboxing, quota, and security surface.
- **No autoscaling, no preview-per-PR environments, no managed databases, no billing.** Each of those is a product in its own right. None of them are why I built this.
- **No Kubernetes.** A homelab is one to a few nodes. Swarm's simplicity is a feature, not a limitation, at that scale.

The non-goals list in the README is longer than some of the feature lists, and that's on purpose.

## Where it is now

koyracloud handles push-to-deploy (a GitHub webhook, optionally gated on CI passing), automatic HTTPS on platform subdomains via Traefik and Let's Encrypt, custom domains via Cloudflare for SaaS, secrets encrypted at rest with Fernet and injected at runtime, live build/deploy logs, one-click rollback, persistent storage, and background workers, cron jobs and a per-app Redis bus — all from the same repo and image. It's running in production today for real client apps.

It's open source under AGPL-3.0. I'm building it in the open because the most useful infrastructure I've ever used was the kind I could read the source of when it broke at 3am. If you've got a homelab and a pile of side projects that never ship because the deploy friction is too high, this is the layer that closes that gap — and I'd love a GitHub star if it resonates.

koyracloud is built and maintained by [Hikmah Technologies](https://hikmahtechnologies.com). The full architecture write-up, including the build/registry/no-pinning reasoning, is in the [repo](https://github.com/hikmahtech/koyracloud).
