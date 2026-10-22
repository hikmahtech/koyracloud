---
one_liner: An open-source, self-hosted PaaS for Docker Swarm. Connect a git repo and it builds a container image and runs it behind HTTPS on your own servers.
for_whom: One operator who runs a Docker Swarm (a homelab, or servers for their own and their clients' apps) and wants "connect a repo, it deploys" without Kubernetes or hand-written compose, Traefik and certificate setup per app.
answers:
  - how do I self-host something like Vercel on my own server
  - open source Vercel alternative for Docker Swarm
  - self-hosted Heroku alternative with workers and cron
  - how do I deploy a FastAPI and React app to my homelab
  - push to deploy from GitHub to Docker Swarm
  - do I need Kubernetes to self-host my apps
  - how do I move a Next.js app off Vercel to my own server
  - custom domains with automatic HTTPS on Docker Swarm with Traefik
  - how do I run cron jobs and background workers on Docker Swarm
does_not:
  - run untrusted code safely; it is single-operator and trusted-code only, with no multi-tenant isolation or sandboxing
  - autoscale apps
  - create a preview environment per pull request
  - provide managed databases (it offers one shared Redis, isolated per app by ACL, and persistent folders)
  - offer a hosted service you can sign up for; "Sign in with GitHub" on koyracloud.com is the owner's own instance behind an allowlist
  - run on Kubernetes or plain Docker; it needs a Docker Swarm (one node is fine) with Traefik in front
  - bill users; there is no billing in the product
links:
  home: https://koyracloud.com/
  docs: https://koyracloud.com/docs                  # manifest reference
  repo: https://github.com/hikmahtech/koyracloud     # main link on devto, bluesky and medium; home on linkedin-page and facebook
disclosure: I built this.
link_wanted: true                                    # open source and free to self-host; the goal is GitHub stars
voice: plain and technical, like an engineer's build log; name the trade-offs and non-goals openly; problem first, koyracloud last; never "enterprise" or "cloud-scale"
content:
  blog_dir: web/src/posts
  format: md                                         # plain Markdown, no front matter and no H1; sections start at "##"
  url: https://koyracloud.com/blog/{slug}
  front_matter: []                                   # none in the file; metadata lives in web/src/posts/index.js
  example: web/src/posts/deploy-fastapi-react-homelab.md
  register: >-
    Add `import x from "./<slug>.md?raw";` and a POSTS entry
    {slug, title, description, date (YYYY-MM-DD), tag, body} at the top of
    web/src/posts/index.js (newest first). Tags in use: Build log, Tutorial,
    Opinion, Guide, Comparison, Feature, Engineering, Essay. The sitemap and
    /blog/rss.xml are generated from POSTS at build (web/prerender.js); the
    "Writing" list in web/public/llms.txt is by hand, so add the post there too.
channels: [linkedin-page, facebook, bluesky, devto, medium]   # developer and homelab audience
# Company accounts only (owner, 2026-10-22): never the personal LinkedIn (`linkedin`) or a personal
# Facebook profile. devto and medium are personal-name accounts: how-to articles only, with the
# product only as the canonical link.
---

## Positioning

koyracloud turns a Docker Swarm into a small Platform-as-a-Service for one operator. You
commit a short manifest (`.paas/app.yaml`) or point it at your own `Dockerfile`, connect the
repo, and it deploys. Each deploy clones the repo, builds a per-app image on local disk,
pushes it to a built-in registry and runs it as a Swarm service behind Traefik with HTTPS.

The ask in every post is: self-host it, and star the repo. A post that promotes a blog post
links the post on koyracloud.com; otherwise dev.to, Bluesky and Medium link the repo, and
the LinkedIn and Facebook pages link the site.

What it does today (code: `control-plane/koyracloud/`):

- Runtimes: `python`, `node`, `python+node`, `static`, `go`, or `dockerfile` (`manifest.py`).
- Every app gets a `<name>-<token>.<apps domain>` URL with automatic TLS. Custom domains go
  through Cloudflare for SaaS when it is configured, otherwise Traefik's Let's Encrypt resolver.
- Push-to-deploy from a GitHub webhook, on `push` or only after CI passes (`workflow_run`).
- Live build and deploy logs, deploy history, one-click rollback.
- Secrets encrypted at rest (Fernet), injected at run time, not baked into images.
- `persist:` folders that survive redeploys (NFS-backed on multi-node swarms).
- Background `workers`, `cron` jobs with run history and a Run now button, and a shared Redis
  with one ACL user per app (`redisbus.py`, `scheduler.py`).
- Cookieless page analytics per app (`analytics.py`) and an uptime monitor with email alerts
  through Resend when configured (`monitor.py`, `notifier.py`).
- Sign in with GitHub through a GitHub App, deploy your private repos, invite members from the
  Team page, admin API tokens.
- `koyra validate` checks a manifest locally before you push.

It is deliberately small. The non-goals are stated in the README and should be stated in posts
too: no multi-tenant isolation, no autoscaling, no preview-per-PR, no managed databases, no
billing. "Trusted code, one operator" is the idea that keeps it simple.

Status: alpha, version 0.1.0 (`CHANGELOG.md`). Open source under AGPL-3.0 at
github.com/hikmahtech/koyracloud.

It runs in production on the owner's homelab swarm: koyracloud.com itself, Hikmah's own sites
ansaar.in (markets research), domainposture.com and quantamentry.com (macro data), and two
client sites, manasrealty.com and vcsolutions.co.in. Call only those two "clients".

The blog (12 posts, June 2026) covers self-hosting a PaaS, Swarm versus Kubernetes, moving off
Vercel and Heroku, and the engineering choices (images, not code on NFS). Each post ends with a
"Star on GitHub" box and a "Built by Hikmah Technologies" line.

## How it is offered

- **Self-host, free.** Clone the repo, fill `deploy/koyracloud.env`, run `deploy/install.sh`.
  This is the path every post points to.
- **Commercial licence.** For anyone who wants to host it as a service or embed it without the
  AGPL's network-copyleft (`LICENSING.md`). Contact by email; no price is public.
- **Managed koyracloud.** The landing page keeps a waitlist for a hosted version. Posts never
  mention it: no hosted version exists, and nobody has joined the waitlist.

## Pricing

No public prices. Self-hosting is free under AGPL-3.0. The commercial licence has no published
price.

## Words and claims to avoid

- "Sign up", "get started free", "try it now" as if koyracloud.com were a hosted service. A
  stranger who signs in gets a 403 ("is not allowed"). Say "self-host it" and link the repo.
- "Hosted", "managed", "unlimited sites", "join the waitlist": the managed service is not a
  talking point.
- "Secure multi-tenant", "sandboxed", "isolated" for apps: it is trusted-code only. Redis is
  isolated per app by ACL; say exactly that.
- "Autoscaling", "preview deployments", "managed Postgres": non-goals.
- "Kubernetes" as something it runs on; it runs on Docker Swarm.
- "Production-ready", "battle-tested", "enterprise": it is alpha 0.1.0.
- "No NFS needed" without "on a single node": multi-node swarms need an NFS export.
- "Vercel clone" or implying Vercel features beyond the git-to-URL loop (edge functions, a CDN,
  image optimisation). Use "your own Vercel" only the way the site does: the deploy experience.
- "Our clients" for ansaar.in, domainposture.com or quantamentry.com: they are Hikmah's own.
- Numbers from the old posts ("a month", "15% utilised", "80% of the complexity") unless the
  owner confirms them for the new piece.
- Star counts: quote the current number only, with its date.
- Hype words: "revolutionary", "blazing fast", "powerful", "AI-powered".
