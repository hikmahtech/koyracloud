Most production apps aren't just HTTP servers. They need a worker chewing through a queue, a nightly task dumping old logs, maybe a poller checking an external API. That's usually where complexity snaps in—a separate worker codebase, a different deploy pipeline, environment variables in three places, a Redis instance you're guessing about. koyracloud collapses that. The same image that runs your web app runs your workers and cron jobs. The same secrets, the same Redis instance, all declared in a single `.paas/app.yaml` manifest.

This matters because it cuts the places where things can drift. Your worker and your web app share the same source code, the same environment, the same deployment instant. There's no "oops, I forgot to redeploy the worker" or "why is the worker running an old version of that function?" If the web service is healthy, so are the workers.

## Workers: Always-On Queue Consumers

A worker is an extra process born from the same image, with no HTTP port. Usually it's sitting on a queue—Redis, RabbitMQ, whatever your app talks to—pulling jobs and running them.

In the manifest, you declare it by name and command:

```yaml
redis: true

workers:
  - name: events
    start: python -m app.worker
    replicas: 1
  - name: emails
    start: python -m app.queue.email_sender
    replicas: 2
```

Each worker gets its own Swarm service off the single built image. They inherit the app's environment variables, secrets, and the `REDIS_URL` (if `redis: true`). They don't run the web app's `predeploy` hook—no database migration on worker startup—so cold starts stay fast.

You can tune `replicas` (default 1) and optionally set CPU/memory limits. No health checks, because workers aren't supposed to be idle and responsive. If a worker dies, it just dies; the Swarm daemon restarts it.

The dashboard shows worker status and lets you tail logs per-worker. Useful when one worker is wedged and the others are fine.

## Cron: Run-to-Completion Jobs

Cron jobs are Swarm run-to-completion tasks, not perpetual services. They launch on a 5-field UTC schedule:

```yaml
cron:
  - name: nightly
    schedule: "0 2 * * *"
    command: python -m app.jobs.nightly
  - name: hourly_sync
    schedule: "0 * * * *"
    command: python -m app.tasks.sync_upstream
```

Each job is created from your *current live image*—the one running your web app right now. The control plane watches the schedule, fires the job at the right moment, and captures its exit code and logs.

You get a run history in the dashboard: timestamps, duration, exit code, and full logs. There's also a "Run now" button, handy for testing or emergency replays.

### The No-Catch-Up Design

Here's where opinions get strong. koyracloud does **not** catch up missed jobs.

Say your app went down for 20 minutes during peak cron time. When it comes back, that missed slot fires once—not once per minute it was overdue. Why? Catch-up storms are worse than skipped runs.

Take a nightly backup job that's 10 minutes overdue by the time your app recovers. A naive catch-up would queue 10 copies at once, each trying to grab an exclusive lock on the backup, fighting for resources, and probably all failing. You've swapped one problem (a missed backup) for a worse one (a cascade).

A single "fire once when things recover" is boring and honest. If that one job fails (and you care), you hit "Run now" and watch the logs. If you need guaranteed-never-skip behavior—a payment reconciliation, compliance task, whatever—you move that into the worker queue where retries and deduplication are explicit, not surprising.

## Redis: Shared but Isolated

koyracloud gives you one Redis instance, shared by all your apps. But you can't see anyone else's data.

When you set `redis: true`, the control plane creates an ACL user for your app (scoped to your app's name) and injects `REDIS_URL` into the environment. Your code connects and operates normally. Internally, every key and channel you touch is filtered: `<app-name>:jobs`, `<app-name>:cache`, etc. Try to read a key without the prefix, or spy on another app's namespace, and Redis rejects it.

The instance runs `noeviction`. Under memory pressure, Redis doesn't silently drop your queued messages like it might with `allkeys-lru`. Instead, it back-pressures with a write error. You notice immediately. Queue overflow becomes visible, not silent.

This is the right default for a single-operator or small-team setup. You're not fighting with a dozen other teams; you want to know when your queues are piling up.

## Putting It Together

A real example. A simple job-posting site:

```yaml
redis: true

workers:
  - name: indexer
    start: python -m app.search.reindex_worker
    replicas: 1

cron:
  - name: stale_cleanup
    schedule: "0 3 * * *"
    command: python -m app.jobs.delete_old_postings
```

One image. One deploy. The indexer worker watches a queue (populated by the web app when a job is posted). The cleanup cron runs at 3am UTC, deletes expired listings, and logs the count. If the cleanup fails, you see it in the run history. If you're testing a fix and want to fire it early, you hit "Run now."

Your database credentials, API keys, everything—all in the same secret store. No separate worker .env file, no "whoops, forgot to sync the key to the worker server."

## Honest Limits

This is built for a single-operator or trusted-team setup. There's no auto-scaling workers based on queue depth—you set `replicas` and live with that capacity. There's no circuit-breaker or bulk job cancellation. If something goes wrong, you ssh in or adjust the manifest and redeploy.

The cron scheduler is local to the control plane. It doesn't store missed jobs or retry across control-plane restarts (though restarts should be rare and transparent). It's elegant for a small domain; it's not Temporal or Airflow.

But for most apps, that's plenty. You get workers and cron without the separate deployment ceremony, the drift, the "wait, which version is the worker running again?"—all from one image, one manifest, one source of truth.

Dig into the [docs](/docs) or check out the [koyracloud repo](https://github.com/hikmahtech/koyracloud) if you want to see the manifest schema or how the control plane manages it all.
