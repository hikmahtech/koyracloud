## Push-to-Deploy, Without the CI Yak-Shave

If you've ever wired up a deploy pipeline, you know the feeling. You open `.github/workflows/deploy.yml`, and suddenly you're knee-deep in YAML: SSH keys, registry credentials, curl requests, kubectl apply or docker-compose calls, waiting for a runner to finish, debugging why the secret didn't interpolate, adding retry logic, monitoring the logs somewhere else. It works—eventually—but the whole stack feels like overhead when what you actually want is "push my code, it builds, it runs."

koyracloud takes that familiar pain and removes the boilerplate. Connect a GitHub repo, push a commit, and your app builds and deploys automatically. The pipeline is simple enough that it doesn't need a thousand lines of YAML to exist.

## How It Works: The Pipeline

Here's what happens under the hood when you push:

```
Push commit to GitHub
       ↓
Webhook fires (or workflow_run event)
       ↓
koyracloud clones repo at that commit
       ↓
Builds Docker image (Docker layer cache speeds things up)
       ↓
Pushes image to internal registry (a Swarm service)
       ↓
Updates the Swarm stack with new image + runtime config
       ↓
Swarm pulls image, starts container(s), routes traffic
       ↓
App is live (build + deploy logs streamed to dashboard)
```

The control plane does the heavy lifting: it manages the build, the registry push, and the Swarm deployment. Your app runs anywhere on the cluster—koyracloud picks an available node. If you're running a homelab or a small data center, that might be the same physical machine; if you have multiple nodes, containers get scheduled across them. Traefik (the ingress controller) routes the traffic.

## Fast Rebuilds: Docker Layer Caching

The first build takes time. But the second? Not so much.

Docker caches layers, so if your dependencies haven't changed (your `package.json`, `requirements.txt`, etc.), koyracloud reuses the layer from the previous build. Only the changed code gets rebuilt. On a typical Node or Python app, that's the difference between 90 seconds and 15 seconds. On every push. The difference compounds if your team pushes several times a day.

This only works if the build runs locally on koyracloud's control plane—which it does. You're not waiting for a GitHub Actions runner to spin up or a cloud builder to process the queue; the build happens on the same machine that orchestrates your cluster.

## Two Deployment Modes: Immediate or CI-Gated

koyracloud supports two webhook triggers:

**Push event (immediate):** Any commit that lands gets built and deployed right away. Fast feedback, but if CI is separate, you might ship a broken commit for 30 seconds before realizing the tests fail. Fine for a solo project or internal tools; riskier for production.

**Workflow run event (CI-first):** koyracloud only deploys after your CI (GitHub Actions, whatever) passes. Connect the webhook to the `workflow_run` event, not `push`. Now the deploy is gated behind green tests. No broken commits reach production. This is the comfortable middle ground: you still get automatic deploy, but only when you know the code is solid. Most teams prefer this.

The choice is yours. Neither requires additional deploy steps in the CI config; koyracloud listens passively and acts when the event fires.

## Build-Time Framework Secrets vs. Runtime Secrets

This trips up new deployers, so koyracloud handles it explicitly.

**Build-time secrets** (framework public env vars like `NEXT_PUBLIC_*` in React, `VITE_*` in Vue) are passed as Docker build args. They end up in your client bundle. These are safe to commit (they're not sensitive), and the platform passes them during the build step so your bundler can use them.

**Runtime secrets** (database URLs, API keys, auth tokens) are injected at container start, not at build time. They're encrypted at rest using Fernet, never baked into the image. If you rotate a secret, you redeploy a new container without rebuilding the image. No drift between environments, no secrets leaking into image layers.

You define both in the `.paas/app.yaml` manifest. The platform distinguishes them automatically.

## Pre-Deploy Steps: Run Before the App Starts

Some apps need setup on every deploy: run database migrations, seed data, warm caches, etc. koyracloud supports a `predeploy:` section in the manifest. These steps run on container start before your app's main process begins.

Common example with a Python app:

```
predeploy:
  - alembic upgrade head
  - python manage.py collectstatic
```

Run migrations every time a new container spins up, or every time you redeploy. No manual steps, no "oops I forgot to migrate the prod database."

## Live Logs and Rollback

While the build and deploy happen, logs stream to the dashboard over Server-Sent Events (SSE). You watch it happen in real time: the `docker build` output, the push to registry, the Swarm service update, the container starting up. If something breaks, you see it immediately.

If it does break—or if you realize a deploy is bad after the fact—one click rolls back to the previous image. The old container spins up while the new one shuts down. Your app is live again on known-good code. This beats manually tagging an old image or hunting through git history.

## The Honest Limits

koyracloud assumes a few things about your setup:

- **You control the infrastructure.** Single data center, homelab, a few cloud instances you own. Not a managed SaaS where autoscaling and global distribution matter.
- **You're okay with a single build machine.** Builds are sequential, not parallel. If two developers push at the same time, one queues. For a small team, this is fine; for high-frequency CI/CD at scale, this isn't the answer.
- **You manage the base infrastructure yourself.** No magic: you provision nodes, monitor them, keep them patched. koyracloud orchestrates the app, not the cluster.

If those constraints fit, the payoff is real: no YAML boilerplate, no SSH jumping, no manual registry management. Push, deploy, done.

## One Less Thing to Maintain

What makes this model pleasant is mostly what it doesn't require. No GitHub Actions deploy steps. No SSH secrets in CI. No separate webhook router. No registry authentication to wire up. You get the push-and-deploy loop of Vercel or Heroku, running on your own iron.

For teams who've outgrown managed platforms but don't have the headcount to run a full Kubernetes cluster, koyracloud's push-to-deploy fills a gap that's usually either "I'll do it manually" or "I'll wire up a complex CI pipeline." Neither is great.

See the [self-host tutorial](https://github.com/hikmahtech/koyracloud/blob/main/docs/SELF-HOST-TUTORIAL.md) or explore the GitHub repo for details on setting up your own instance.
