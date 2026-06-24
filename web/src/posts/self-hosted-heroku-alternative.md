If you spent years pushing code to Heroku and watching it Just Work, you know what you're missing now: that frictionless `git push heroku main` → live app loop. The platform abstracted away servers, databases, and most of the ops work. For side projects, internal tools, and client apps, it was genuinely hard to beat.

Then the free dynos disappeared, and a lot of people realized they were paying $50/month for something that could run on their own hardware for almost nothing. That's where koyracloud comes in. It's an open-source, self-hosted PaaS built on Docker Swarm that brings back the Heroku workflow—without the managed-services markup and without a vendor telling you when to stop.

## The Familiar Loop

Push code. Get a deploy. Check logs in the UI. Roll back with one click. No SSH into production, no manual docker-compose wrangling.

koyracloud hooks into GitHub: every push or green workflow_run triggers a deploy. You see live logs streaming in the browser (Server-Sent Events), a full deploy history, and one-click rollbacks if something breaks. It's the same mental model. You're not managing containers; you're describing your app.

## From Procfile to `.paas/app.yaml`

Heroku's `Procfile` told the platform what processes to run:

```
web: gunicorn app:app
worker: celery -A app.celery worker
clock: celery -A app.celery beat
```

In koyracloud, that's replaced by a manifest at `.paas/app.yaml`:

```yaml
runtime: python:3.12
port: 8000
build:
  - pip install -r requirements.txt
predeploy:
  - alembic upgrade head
start: gunicorn app:app
healthcheck:
  path: /health
  interval: 30s
workers:
  - name: celery-worker
    command: celery -A app.celery worker
    replicas: 2
    cpu: 0.5
    memory: 512Mi
cron:
  - name: cleanup-old-records
    schedule: "0 2 * * *"
    command: python -m tasks.cleanup
redis: true
persist:
  - /data
```

It declares everything: runtime (bring your own Dockerfile or use a buildpack), build steps, the start command, workers, cron jobs, Redis, persistent storage, even healthchecks. If you've configured Heroku dynos, this will feel natural—just more explicit and more flexible.

## Secrets Over Config Vars

Heroku had "config vars"—`DATABASE_URL`, `SECRET_KEY`, and friends, set through the web UI or CLI. koyracloud has `secrets:` in the manifest, also injected at runtime and encrypted at rest using Fernet. Set them in the dashboard, and they're available to your app on boot.

Same idea. Different URL.

## Workers, Not Dynos

Heroku's worker dynos were always-on processes sharing the same image as the web dyno. koyracloud has `workers:` for the same thing: queue consumers, bots, background tasks that need continuous execution. Specify replicas, CPU, and memory allocation. You get fine-grained control without learning Kubernetes.

## Release Phase Becomes Predeploy

Heroku's `release:` process (e.g., `release: alembic upgrade head`) ran once per deploy, after the build, before the web process started. In koyracloud, that's `predeploy:`, same semantics. Your migrations run before traffic switches over.

## Scheduler Without the Catch-Up

Heroku's Scheduler add-on let you run one-off tasks on a cron schedule. It had one quirk: if you had downtime and missed a slot, it would sometimes catch up with multiple runs. koyracloud's `cron:` jobs are simpler: they run on UTC schedules (5-field format), launch as Swarm run-to-completion jobs from your live image, and—importantly—don't catch up. Miss a slot during downtime, and the next scheduled window fires once. No surprise bursts.

Each cron job has a status view, logs per run, and a "Run now" button for testing.

## Redis, But Not Heroku's Add-On

Heroku's Redis add-on gave you a managed Redis instance. koyracloud has `redis: true` in the manifest, which provisions a Redis container isolated to your app. It injects `REDIS_URL` automatically and runs with `noeviction` policy—meaning it back-pressures rather than silently dropping keys. That's actually nicer than Heroku's defaults, because you'll know if your queue is getting full.

## Persistent Storage (A Real Difference)

Here's something Heroku *didn't* have: `persist:` directories in the manifest. These are NFS-backed volumes that survive redeploys and container restarts. Want to keep uploaded files, local caches, or SQLite databases? Mount a path in `persist:` and it stays.

Heroku's filesystem was ephemeral—every dyno restart wiped it. If you needed permanent storage, you bought a database add-on or wrote to S3. This is a genuine advantage of the self-hosted model.

## Honest Trade-Offs

Heroku spoiled you in a few ways worth acknowledging. It had a whole add-on marketplace: Postgres, Redis, Elasticsearch, etc., all managed for you. One command, one bill. koyracloud has no Postgres add-on; if you need a database, it's on your swarm or external. No autoscaling, no multi-tenant sandboxing for untrusted code, no built-in billing or team features.

What you *do* get: full control, no vendor lock-in, no surprise bill as you scale, and the ability to run on whatever hardware you own. It's a trade. It makes sense for internal tools, side projects, and client apps where you trust the code and you're the operator.

## The Missing Piece

The real thing Heroku did well—the thing worth being nostalgic about—was making servers disappear from your thought process. You pushed code. The platform handled the rest. koyracloud brings back that workflow, but you own the infrastructure: a Docker Swarm cluster somewhere, probably on your own metal or a cheap VPS.

That's not for everyone. But if you're the type who remembers `git push heroku main` with fondness and groans at the idea of managing Kubernetes, or if you're tired of paying Heroku's premium for simple deployments, koyracloud might feel like an old friend.

You can find it at [github.com/hikmahtech/koyracloud](https://github.com/hikmahtech/koyracloud), or read the [deployment docs](/docs) for setup and the full manifest reference.