Moving a Next.js app off Vercel onto your own hardware is mostly easy and has two genuinely fiddly parts: the Dockerfile, and the apex domain. Everything else is a manifest. This is the field-tested version — the traps we actually hit moving real apps onto koyracloud, not the happy path.

## First, pick a strategy

Two ways to run a Next.js app, and the choice decides everything downstream:

- **Static export** (`output: 'export'`) — if your app has no server-side rendering or API routes at request time, it builds to plain static files. Simplest to host, nothing to keep running. One non-obvious requirement: set **`trailingSlash: true`**. Static export emits `about/index.html`, and without trailing-slash routing the URLs don't resolve cleanly behind a static server. It's not optional; it's the thing that bites everyone.
- **Node SSR** — if you use server components, API routes, or ISR, you need the Node server running. That means your own Dockerfile, which Vercel was hiding from you.

koyracloud supports both: `runtime: static` for the export, or `runtime: dockerfile` (bring your own) for SSR.

## The Node-SSR Dockerfile

Vercel never made you write one, so here's the shape that works: a multi-stage build, `output: 'standalone'` in `next.config.js`, copy the standalone output and static assets into a slim `node:alpine` runner. Two things reliably go wrong:

- **Public env vars must be inlined at build.** Anything `NEXT_PUBLIC_*` is baked into the client bundle when `next build` runs — not read at runtime. koyracloud passes your app env as `--build-arg`, so declare and `ENV` each `NEXT_PUBLIC_*` in the build stage. Miss one and it ships as `undefined` in the browser.
- **Pin your package manager.** The single most common failure is a pnpm/npm version mismatch between your machine and the build. Pin it (`packageManager` field, or a corepack step) so the lockfile resolves identically. Also budget for `next/font/google` reaching out at build, and `sharp` needing its platform binary in the runner stage.

One koyracloud-specific note: **don't set `healthcheck:` on an own-Dockerfile `node:alpine` app** unless you've added a tool to hit it — alpine ships without curl/wget and the check will fail the app that's actually healthy.

## The manifest

For an SSR app with your own Dockerfile:

```yaml
name: my-site
runtime: dockerfile
port: 3000
secrets: [DATABASE_URL, RESEND_API_KEY]
```

Monorepo? Point at the subdirectory with `root: apps/web` and koyracloud builds from there. Env and secrets you set in the dashboard — values are encrypted at rest and injected at runtime. Watch for **two quoting traps** when copying env out of Vercel: values with `$` or with surrounding quotes get mangled if you paste them raw. Set them deliberately, not by bulk-paste.

## Deploy on the free URL first

Before you touch DNS, deploy and verify on the automatic `my-site-<token>.<apps domain>` URL. Click through the app, check the API routes, confirm the client-side env actually resolved. Get it fully green there. *Then* deal with the domain — never cut DNS over to an unverified deploy.

## The apex problem

Here's the part that's genuinely annoying, and it's not koyracloud's fault — it's how DNS works. Custom subdomains are easy: koyracloud registers them as Cloudflare for SaaS custom hostnames, you add two CNAMEs at your registrar, and the edge mints and renews the certificate. Vercel-style, hands-off.

But `example.com` with no `www` — the apex — **can't be a CNAME** in classic DNS. So you have four options, in rough order of preference:

1. **Use a DNS provider with CNAME-flattening / ALIAS records** (Cloudflare, others) — point the apex at the target as if it were a CNAME. Cleanest.
2. **Redirect apex → `www`** and serve everything on `www`, which *can* be a CNAME. A one-line redirect rule at the edge.
3. **Serve on `www`, redirect apex** the other direction if you prefer the bare domain canonical — same mechanism, reversed.
4. **A records to fixed IPs** as a last resort, if your edge has stable addresses.

Most people want option 1 or 2. The decision you're really making is *serving vs redirecting the apex* — pick which hostname is canonical and make the other one redirect, so you don't split SEO or cookies across two origins.

## Don't forget email

The trap that turns a smooth migration into an incident: moving DNS to a new provider can silently drop your `MX` and email-auth records. Before you change nameservers, copy every `MX`, `SPF`, `DKIM` and `DMARC` record across. Email going dark an hour after a deploy is a bad afternoon, and it has nothing to do with the app.

## The shape of the whole thing

Strip away the two fiddly parts and migrating off Vercel is: write a manifest (or a Dockerfile for SSR), set your env and secrets, deploy and verify on the free URL, then wire the domain with the apex strategy that fits your DNS. You trade Vercel's zero-config polish for owning the stack — no per-seat pricing, no build-minute meter, and your code and data never leave your hardware.

The full playbook with copy-paste Dockerfiles and every command spelled out lives in [`docs/MIGRATING-FROM-VERCEL.md`](https://github.com/hikmahtech/koyracloud) in the repo. koyracloud is open source (AGPL-3.0), built by [Hikmah Technologies](https://hikmahtechnologies.com) — and if it gets you off a cloud bill, a star helps other people find it.
