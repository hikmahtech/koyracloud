Most people with a homelab have the same problem: a piece of hardware that costs real money to run, has decent CPU and RAM, and sits around 15% utilized, running three containers that probably didn't need to be containerized in the first place.

The gap between "I own this server" and "I can deploy to it like Vercel" is real. You've got the plumbing, but you're hand-writing the plumbing. Every new side project means a new compose file, a new reverse-proxy rule, a new certificate, a deploy script that might work on your machine, probably won't work next Tuesday. The operational tax is so high that new ideas stay in your head because shipping them costs a week of yak-shaving.

This is the homelab that doesn't quite pay for itself.

## The Gap

A Docker Swarm can scale to dozens of nodes, but most homelabs are one or two machines. Kubernetes is right out. Docker Compose is easy, but you end up with brittle shell scripts and manual DNS entries. You need Traefik for HTTPS termination, ACME for certs, NFS for state, container registry auth, a health-check strategy. By the time you've done it right, you've spent a month learning infrastructure and you're exhausted.

The irony is that your metal is capable. A i7 from five years ago, 32GB RAM, and a gigabit NIC can run a lot of real software. But the friction between "I wrote this app" and "it's running somewhere people can use it" is still higher than it should be.

The dream is Heroku or Vercel: connect a GitHub repo, push a commit, thirty seconds later it's live. No container registry auth. No DNS. No cert renewal. No systemd unit files. No SSH and manual restarts.

## What Closing the Gap Looks Like

What if your homelab felt like that? Not the full Heroku experience—no auto-scaling, no managed databases, no preview environments, no multi-tenant isolation. But the core: point a repo, it builds, it deploys, it stays running, you get live logs, you can roll back, and the next app takes the same thirty seconds.

That's the layer you're missing. Not Kubernetes. Not raw Docker. Something in between. A thin operator's layer that handles HTTPS, DNS, storage, container registry, health checks, rollbacks, and background jobs. One person, trusted code, internal or client apps.

The setup cost is real—you still need Traefik, NFS, a domain with wildcard DNS, GitHub OAuth. But you set it up once. Then every app after that costs nothing. A new side project goes from two weeks of yak-shaving to "I wrote a Python script and pushed it; it's now at myapp.my-domain.com with a real certificate and a Redis backend."

Over a year, a homelab like that pays for itself in time saved alone. The hardware stops being a expensive hobby and becomes actual infrastructure.

## The Honesty

This isn't multi-tenant SaaS. There's no user isolation, no billing system, no way to sell compute to strangers. That's intentional. A homelab PaaS is for you, your team, your clients, or projects you trust. It's for internal tools, side projects, personal services. If your threat model is "I need to run untrusted code from arbitrary users," this isn't it. Nor is there auto-scaling or managed databases or any of the full-cloud features. You're still running on your hardware. When it gets full, you get paged and you add more servers.

What you do get: the convenience layer removed. No more hand-writing configuration. No more replaying the same Traefik steps and cert management for every app. No more manual deploy scripts that break when you upgrade Docker. Your homelab, but with the tedium removed.

## Actually Doing It

The implementation isn't magic. It sits between your Swarm and your apps: a control plane that watches your repos, builds images, manages persistent storage, wires up HTTPS and DNS, injects secrets, handles rollbacks. It's open-source, AGPL-licensed, built for real production use. The setup is straightforward: a few machines running Swarm, Traefik already handling certs, NFS exporting storage, and the control plane managing deployments.

The self-host tutorial walks through it: bare machines, Swarm bootstrap, Traefik setup, then adding the deploy platform and shipping your first app. For most setups, it's an afternoon's work.

## The Payoff

Your homelab becomes a deployment platform. New ideas don't stay in your head because they're too much friction to ship. You write code, push to GitHub, and ninety seconds later it's live with HTTPS and a real domain. Existing side projects move off shared hosting or free tiers and onto your own metal. Client apps that would have needed a Heroku invoice or a VPS instead run on your hardware, managed by a single control plane.

The server stops being a status symbol and becomes a tool that actually pays its hosting costs, in convenience if nothing else.

If that appeals to you, the full self-hosting setup is documented in the project repository. It's not a click-next installer—you're on your own hardware, after all—but it's straightforward, and the effort is front-loaded. The payoff compounds every time you ship something new.

The homelab that finally earns its keep.