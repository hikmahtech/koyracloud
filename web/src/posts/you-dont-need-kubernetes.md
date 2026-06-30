Every time someone says "I want to self-host my apps like Vercel," the internet says "learn Kubernetes." For a homelab, or a single operator running internal and client apps, that's advice that costs you a month and pays you back in YAML and on-call anxiety. You almost certainly don't need it.

This isn't a Kubernetes-is-bad argument. Kubernetes is extraordinary at the problem it was built for: many teams, many services, elastic fleets, untrusted workloads, autoscaling, the works. The point is narrower. The thing most people actually want — push a repo, get a URL with HTTPS — does not require any of that machinery, and the machinery isn't free.

## What "I want a PaaS" usually means

When someone wants their own Vercel or Heroku, they want a specific loop:

- Connect a git repo, push a commit, and a minute later it's live.
- HTTPS and a domain appear without thinking about certificates.
- Secrets get injected, data persists across deploys, you can roll back.
- Maybe a background worker and a cron job from the same repo.

That's it. That's the whole job. Nothing in that list says "I need a distributed scheduler with admission controllers and a CNI plugin."

## What Kubernetes asks in return

To get that loop on Kubernetes, you sign up for the control plane (etcd, api-server, scheduler, controller-manager), a CNI network plugin, an ingress controller, cert-manager, a storage provisioner, and usually Helm or Kustomize to keep the YAML survivable. Then you keep all of it patched and upgraded. On a managed cloud, a lot of that is hidden — but you're paying a cloud bill, which is the thing you were trying to avoid by self-hosting. On your own metal, you own every layer.

For a fleet of fifty services across three teams, that's a worthwhile trade. For one or two machines in a closet running your side projects and a handful of client apps, you've taken on a second full-time system to babysit the first.

## Docker Swarm is the boring middle

In between "brittle hand-written compose files and shell scripts" and "full Kubernetes" sits Docker Swarm. It's built into Docker. `docker swarm init`, join your nodes, and you have a scheduler that handles service placement, rolling updates, health checks, overlay networking, secrets, and rescheduling when a node dies. It is dramatically less to learn and operate, and at homelab scale it does everything you need.

Swarm gets unfairly dismissed because it doesn't scale to Google. But you're not Google. You have a homelab. The relevant question isn't "which scales further," it's "which is the least machinery that solves my actual problem." For one trusted operator, Swarm wins on every axis that matters: setup time, cognitive load, and the number of things that can wake you up.

## The thin layer that closes the gap

Swarm gives you orchestration, but it doesn't give you the *PaaS loop*. You still need to clone repos, build images, wire up Traefik routes and certificates, manage a registry, inject secrets, handle rollbacks. That's the layer koyracloud adds — a single control-plane service that sits on top of your Swarm and turns it into a "connect a repo and it deploys" platform:

```yaml
name: my-app
runtime: python+node
port: 8000
build:
  - pip install -r requirements.txt
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
healthcheck: /health
```

Commit that, connect the repo, and koyracloud builds a per-app image, pushes it to a built-in registry, and deploys a Swarm service behind HTTPS — with secrets, persistence, custom domains and push-to-deploy. No Helm charts. No `kubectl`. No cluster to upgrade.

## When you *should* reach for Kubernetes

To be fair to the other side: if you're running untrusted multi-tenant workloads, need real autoscaling under spiky load, have multiple teams that need namespace-level RBAC and isolation, or you're operating at a scale where a dedicated platform team is justified — Kubernetes earns its complexity. koyracloud deliberately doesn't do those things; it's single-operator, trusted-code, internal-apps by design, and the non-goals list says so plainly.

But that's not most homelabs, and it's not most small studios running a dozen client apps. For them, the honest answer to "do I need Kubernetes to self-host my apps?" is no. You need a Swarm and a thin layer on top of it — and you can have the whole thing running in an afternoon.

koyracloud is open source (AGPL-3.0), built by [Hikmah Technologies](https://hikmahtechnologies.com). If "you don't need Kubernetes for this" is a relief to hear, the [repo](https://github.com/hikmahtech/koyracloud) is a star away.
