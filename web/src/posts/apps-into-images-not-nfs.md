When we started koyracloud, the natural architecture felt obvious: keep each app's code, node_modules, and venv on a shared NFS volume. A one-off container would land on that volume, build the dependencies in place, and then a long-running service would serve the code directly from there. To avoid rebuilding every time, we hand-rolled a dependency hash check—does the lockfile match what's cached here? If yes, skip the build.

It worked fine for small deployments and light traffic. But as the platform grew, something unexpected happened: NFS became our bottleneck, and not in a fun way.

## The NFS Many-Small-Files Problem

NFS is architected around network round-trips. It handles large files reasonably well. But a node_modules tree (or a Python venv) is thousands of tiny files living in nested hierarchies. Every time the build container walked the directory tree to check what existed, or the app container listed a directory, NFS had to make a network call and wait for metadata.

When we triggered a build—especially a heavy one that needed to download and extract packages—the I/O traffic exploded. The NFS server spiked. That's expected and manageable at first. But what wasn't expected was what happened to the control plane.

The control plane's database lived on the same NFS volume. When builds crawled and hammered the NFS server, the database couldn't get the I/O it needed. Healthchecks started timing out. And a few times, mid-deploy, the control plane would fail its own healthcheck, crash, and take the entire deployment with it.

We'd essentially built a way for app deployments to knock over the platform itself.

The hand-rolled dependency hashing didn't help much either. We were checking file mtimes and computing hashes, which meant traversing the same directory trees that were causing I/O contention in the first place. More trips to NFS, more pain.

## The Image-Based Rewrite

The fix was to flip the model upside down.

Instead of building dependencies onto a shared NFS volume, we build each app into a Docker image. The build happens on the node's local disk—fast, no network overhead, no contention with the control plane. Once the image is built, we push it to a built-in internal registry (a `registry:2` service running as a Swarm stack). Then we tell Swarm to run the app from that image.

The flow looks like this:

```
repo → clone to local build dir → docker build → docker push → docker stack deploy → pull + run on any node
```

Any Swarm node can pull and run the image. Apps are no longer pinned to a specific build node. They can reschedule on any healthy node, any time. NFS is now touched only for what it's actually good at: persisted application data (the `persist:` directories in the manifest) and the registry storage itself (which is read-heavy and batched, not a hotly-contested I/O workload).

Docker's layer cache replaces our hand-rolled hashing. If the dependencies haven't changed, the layer is already there. If they have, Docker rebuilds just that layer. It's simpler, faster, and doesn't require us to maintain sync logic.

## Why This Is Cleaner

A few wins fell out of this:

**No blast radius to the control plane.** Builds run on local disk. Heavy I/O doesn't starve the database. You can deploy apps without risking the platform.

**Cache that actually works.** Docker layers are a proven, efficient caching mechanism. We didn't have to maintain our own hashing and sync logic. That code is gone—one of those rare refactors where we removed more than we added.

**Reschedulability.** Apps run from images, not live code on a volume. A node goes down, Swarm pulls the image on another node and keeps going. No fiddling with NFS mount states or waiting for volume mounts to settle. No tying apps to specific hardware.

**Isolation.** Each deploy gets its own image. If something goes wrong with one app's build, it doesn't affect others. If you need to roll back, you're just running a different image. Clean.

## The Trade-offs We Accepted

We do maintain an internal registry now, which is another service to keep alive. The registry itself stores blobs on NFS (or any persistent backend), but the access pattern is different—mostly reads, batched, and not the fine-grained metadata hammering that killed us before.

Builds take a few more seconds per deploy because of the push step. But they're no longer fighting I/O contention on a shared volume, so the total time is faster and more predictable.

We had to think through image garbage collection—don't want the registry filling up over time—but that's a solved problem with a quick policy.

## The Outcome

The platform is now resilient in a way it wasn't before. Deploying apps doesn't risk the control plane. Builds are predictable. Apps can run anywhere and reschedule freely. We have less custom code to maintain. The failure mode that could take the whole platform down is gone.

Sometimes the obvious first design teaches you something. In this case, it taught us that NFS and many-small-files are fundamentally at odds, and that Docker images are a better unit of deployment than live code on a shared volume. Worth the rewrite.

For more on how koyracloud orchestrates deploys and manages images, see the [architecture docs](https://github.com/hikmahtech/koyracloud).