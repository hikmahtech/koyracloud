# Migrating a Next.js app from Vercel to koyracloud

A field-tested playbook, distilled from migrating a fleet of real apps (static
marketing sites, a multilingual SPA-ish site, and full SaaS apps with Auth.js +
Drizzle/Neon + Razorpay/PayPal + Inngest + S3 + Resend + MCP). Every gotcha below
cost a failed deploy at least once.

## TL;DR

1. Pick a strategy: **static export** (no server) or **Node SSR** (own Dockerfile).
2. Add a `.paas/app.yaml` manifest + (for SSR) a `Dockerfile`, commit them to the repo.
3. Create the app on koyracloud, set env + secrets, deploy to the free
   `<name>-<token>.koyracloud.com` URL and verify.
4. Cut the real domain over (DNS), preserving any email records.
5. Delete the Vercel project.

The manifest travels with the code, so redeploys are reproducible.

---

## 1. Choose a strategy

| | **Static export** | **Node SSR (own Dockerfile)** |
|---|---|---|
| When | No API routes, SSR, server actions, ISR, middleware, or `headers()/redirects()` that need a server | Anything with a backend surface, auth, DB, payments, ISR, middleware |
| next.config | `output: 'export'` + `trailingSlash: true` + `images.unoptimized: true` | `output: 'standalone'` |
| `.paas/app.yaml` | `runtime: static`, `static_dir: out` | `runtime: dockerfile`, `dockerfile: Dockerfile` |
| Server cost | none (served by the built-in static server) | one always-on container |

**Audit before deciding** — grep the repo for: `app/**/route.*` (API routes),
`'use server'`, `export const dynamic|revalidate`, `runtime = 'edge'`,
`middleware.ts`, `async redirects()/headers()`. Any hit ⇒ Node SSR.

### `trailingSlash` is mandatory for static export

koyracloud's static server resolves `/x/y` to the directory `x/y/index.html`,
falling back to the root `index.html` for unknown paths — it does **not** try
`y.html`. Next's default export emits `out/x/y.html`, so without
`trailingSlash: true` every sub-route serves the home page. With it, the export
emits `out/x/y/index.html`, which serves correctly.

A dynamic route (`[id]`) under static export needs `generateStaticParams()`. If
the page is a Client Component, split it: a Server Component `page.tsx` that
exports `generateStaticParams` + `dynamicParams = false` and renders a client
child.

---

## 2. The Node-SSR Dockerfile (standard, copy-paste)

```dockerfile
# ---- build ----
FROM node:22-alpine AS builder      # node:20-alpine if the app pins <22
WORKDIR /app
RUN apk add --no-cache libc6-compat && corepack enable
COPY package.json package-lock.json ./   # or pnpm-lock.yaml / yarn.lock
RUN npm ci                                # or pnpm install --frozen-lockfile
COPY . .
# Public vars must be inlined into the client bundle at build; koyracloud passes
# the app's env vars as --build-arg, so declare + export each NEXT_PUBLIC_* one.
ARG NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- runner ----
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
```

**`ENV HOSTNAME=0.0.0.0` is not optional.** Next's standalone server binds
`localhost` by default; without `0.0.0.0`, Traefik can't reach the container and
the task looks up but serves nothing.

`output: 'standalone'` must be set in next.config or `.next/standalone` won't exist.

### pnpm version pinning (very common failure)

- `corepack` pulls the **latest** pnpm, which can be incompatible with the node
  base. **pnpm 11 on node:20 fails** with `ERR_UNKNOWN_BUILTIN_MODULE` — pin a
  known-good version.
- **Lockfile `lockfileVersion: '9.0'` → pnpm 9** is the native match:
  `corepack prepare pnpm@9.15.9 --activate`.
- **But** if `pnpm-workspace.yaml` carries pnpm-10-style settings (e.g.
  `ignoredBuiltDependencies`) with **no `packages:` field**, pnpm 9 rejects it
  with `packages field missing or empty`. That project needs **pnpm 10**:
  `RUN npm install -g pnpm@10`.
- Check `package.json#packageManager`; if present, honor it.

### `next/font/google`, fonts, sharp

- `next/font/google` downloads fonts at build — the build node needs network to
  `fonts.googleapis.com`. koyracloud's build node has it; an air-gapped builder
  wouldn't.
- If the app reads `public/fonts/*.ttf` at runtime (PDF/OG generation), Next's
  standalone tracer may miss them — add
  `outputFileTracingIncludes: { "/**": ["./public/fonts/*.ttf"] }`.

---

## 3. The manifest (`.paas/app.yaml`)

Static:
```yaml
name: my-site
runtime: static
build: [npm ci, npm run build]
static_dir: out
```

Node SSR:
```yaml
name: my-app
runtime: dockerfile
dockerfile: Dockerfile
port: 3000
secrets: [AUTH_SECRET, DATABASE_URL, RAZORPAY_KEY_SECRET]   # names only
```

### Do NOT set `healthcheck:` on an own-Dockerfile (node:alpine) app

koyracloud renders the healthcheck as a `python3 -c …` command (python3 ships in
its *generated* runtime image). A `node:alpine` image has no python3, so the
healthcheck always fails and swarm kills the container — the app starts fine,
then dies. Symptom: service `0/1`, task state `Complete`, logs show the app
"Ready" then nothing. Omit `healthcheck:`; process liveness is enough.

### Monorepo subdirectory apps: `root:`

If the app lives in a subdir of a larger repo (e.g. `marketing/site/` inside a
Python platform repo), put `.paas/app.yaml` at the **repo root** and scope the
build context with `root:`:
```yaml
name: my-site
runtime: dockerfile
root: marketing/site        # docker build context = this subdir
dockerfile: Dockerfile.web  # path relative to root
port: 3000
```
This keeps the context lean and avoids polluting the repo root with a
`.dockerignore` that would break the root project's own build. Name the web
Dockerfile distinctly (e.g. `Dockerfile.web`) if the subdir already ships a
different Dockerfile for another purpose (e.g. an MCP stdio server).

---

## 4. Env & secrets

- **Public, build-time vars** (`NEXT_PUBLIC_*`, `VITE_*`) → set as **app env** in
  the koyracloud UI. koyracloud passes app env as `--build-arg` (declare matching
  `ARG`/`ENV` in the Dockerfile) **and** injects it at runtime.
- **Server secrets** → koyracloud **secrets** (encrypted, runtime-only, never a
  build arg). List the names in the manifest; set values in the UI. **Never
  commit values** — not in the manifest, not in the Dockerfile.
- **Does the build need a server secret?** Usually no — but if a module asserts
  an env var at import (e.g. `new URL(process.env.X)` in a layout, or a Zod env
  schema), the build fails collecting page data. Two clean fixes: (a) make the
  module build-safe (`isBuild = process.env.NEXT_PHASE === 'phase-production-build'`,
  fall back to a placeholder), or (b) if it genuinely needs the value at build,
  set it as **env** (not a secret). Don't move a real secret to env just for the
  build unless unavoidable.

### Two quoting traps when copying env from Vercel

`vercel env pull` writes values **quoted** (`KEY="https://…"`).

1. **`docker run --env-file`** keeps the quotes literal → `new URL('"https…"')`
   throws "Invalid URL". Strip surrounding quotes before a local smoke test.
2. **`source`-ing the file in bash** breaks on values containing `&` (`parse
   error near '&'`), silently leaving later vars unset → an empty `NEXT_PUBLIC_*`
   build arg → "Failed to collect page data". For local builds, extract values
   with `grep|cut`, not `source`. (koyracloud's own env setter parses the values
   directly, so it's unaffected — only local testing is.)

A `$` in a value (e.g. a password) needs no special handling on koyracloud — the
deployer escapes `$`→`$$` before `docker stack deploy` (which otherwise fails
with `invalid interpolation format`).

---

## 5. Deploy & verify on the free URL first

Create the app (repo URL + branch), set env/secrets, deploy. Verify on
`<name>-<token>.koyracloud.com` **before** touching DNS:
- home + a few routes return 200 with a valid cert;
- config redirects work;
- a DB-backed page loads (proves the DB connection);
- `/api/inngest` returning **401** is correct (Inngest signs its requests); an
  unsigned GET is supposed to be rejected.

External services (Neon, Inngest, S3, Resend, Razorpay/PayPal, Upstash) all work
off-Vercel — they just need their env/secrets. Webhooks keep working because the
production **domain stays the same** after cutover.

---

## 6. Cutover: the apex problem (and four solutions)

`www.<domain>` is easy: a `CNAME → origin.koyracloud.com` validated by
Cloudflare-for-SaaS (DNS/`txt` DCV). **The apex is the hard part** — a zone apex
can't be a CNAME, and Cloudflare-for-SaaS won't activate a custom hostname that's
served via `A`-records-to-anycast (it returns 409, "DNS target needs to point to
the SaaS zone"). Pick by where the domain's DNS lives:

1. **Registrar domain-forwarding** (GoDaddy, Squarespace): toggle "forward apex →
   www". Zero infra. Squarespace forwarding silently fails if the zone is
   delegated elsewhere (e.g. Google Cloud DNS) or Google Workspace manages it.
2. **AWS Route 53**: `ALIAS` record (apex → a CloudFront distribution that 301s
   to www, with an ACM cert). Route 53's ALIAS is the only thing that lets an
   apex target a CDN. Cheap, serverless, fully scriptable.
3. **Self-hosted redirector** (`deploy/apex-redirect-stack.yml`): a tiny Caddy
   service on the swarm, exposed via a **WAN2** port-forward (`:80→baa:8081`,
   `:443→baa:8443`). The apex `A` record points at the WAN2 IP; Caddy mints a
   Let's Encrypt cert (HTTP-01 works because WAN2:80 is a real inbound path the
   tunnel can't provide) and 301s `<apex>`→`www`. Only the bare apex touches
   WAN2; everything else stays behind the hidden Cloudflare tunnel. Use when the
   DNS host can neither CNAME nor ALIAS an apex (e.g. Google Cloud DNS) and you
   don't want a cloud redirector.
4. **Move the domain's DNS to Cloudflare (best when feasible)**: Cloudflare
   flattens an apex CNAME, so the apex `just works`. Add the zone, point apex +
   www as **proxied (orange) CNAME → origin.koyracloud.com**, change nameservers
   at the registrar. The domain gets its own free Universal SSL; no redirector,
   no CloudFront. koyracloud serves the host with `tls=true` and **no** ACME
   (cert terminates at the Cloudflare edge; the tunnel is `noTLSVerify`).

### Serving vs redirecting the apex

If the canonical host is `www`, redirect apex→www. If the canonical host is the
**apex** (e.g. `AUTH_URL=https://example.com`), serve the apex directly (option 4
does this natively) and redirect `www`→apex.

These host-redirects were Vercel **domain config**, not app code — so they vanish
when you delete the Vercel project. Replicate them. The cleanest app-level way is
**`next.config` host redirects** (don't wrap Auth.js middleware — too risky):
```js
async redirects() {
  return [{
    source: "/:path*",
    has: [{ type: "host", value: "www.example.com" }],  // Next anchors host matches
    destination: "https://example.com/:path*",
    permanent: true,
  }];
}
```
**Always verify locally that the canonical host is NOT matched** (no redirect
loop): `curl -H "Host: example.com" …` must serve (200), `-H "Host:
www.example.com"` must 308→apex.

### Preserve email when moving DNS

Adding a domain to Cloudflare auto-imports existing records — but **double-check
that all email records survive** and change *only* the apex/www serving records.
Real fleets had: Zoho MX, Google Workspace MX, **Mailgun** (`send.*` SES MX +
SPF + `k1._domainkey` DKIM), **Resend** (`resend._domainkey` DKIM), Mailchimp
DKIM, `_dmarc`, and `google/zoho/yandex-verification` TXTs. Touch none of them.

### Wiring koyracloud to serve a custom domain

Add the host as a domain on the app (Traefik router renders for it). For the
Cloudflare-own-zone approach (option 4) the host must NOT be registered as a
Cloudflare-for-SaaS custom hostname in koyracloud's *own* account (same-account
conflict) — add the Domain row directly so the Traefik router renders without
the SaaS registration; the customer zone's Universal SSL provides the cert.

---

## 7. Operational notes

- **Don't poll `/api/deploys/{id}` aggressively during a build.** koyracloud's
  control-plane DB is SQLite; the deployer streams build output as frequent log
  writes, and heavy concurrent reads used to trip `database is locked`. (Fixed
  now via WAL + busy_timeout + atomic single-statement log writes, but still:
  trigger, wait ~150s, check once.)
- **Recover a stuck/orphaned `building` deploy** by force-restarting the
  control-plane: `docker --context swarm-baa service update --force
  koyracloud_control-plane` (clears in-memory locks/threads; running app
  services are unaffected), then re-trigger.
- **First build of a new commit runs on the control-plane node** (baa, mounted
  socket). A redeploy of an already-built commit skips the build and reuses the
  registry image — pure swarm `stack deploy`, any node.
- **DNS/SSL propagation is the long pole.** After a nameserver change, the zone
  goes `active` and Universal SSL provisions automatically (minutes, sometimes
  ~15). `https://<apex>` returning `000`/`tls=1` right after activation is just
  the cert still provisioning, not a misconfig — verify the routing over HTTP
  meanwhile.
- **Vercel Cron → `cron:`; background work → `workers:` + `redis:`.** A Vercel
  Cron Job becomes a `cron:` entry (5-field schedule, UTC) that runs your command
  to completion from the live image. There's no Vercel equivalent of an always-on
  process — for queue consumers/bots use a `workers:` entry, and set `redis: true`
  to get a `REDIS_URL` for the web→worker queue (namespace keys as `<app>:`). See
  the README's "Background workers, cron & Redis".

---

## 8. Pre-flight checklist

- [ ] Strategy chosen (static vs SSR) from an actual repo audit
- [ ] `next.config`: `output` set (+ `trailingSlash`/`images.unoptimized` if static)
- [ ] Dockerfile: right pnpm/node, `HOSTNAME=0.0.0.0`, `ARG`s for every `NEXT_PUBLIC_*`
- [ ] `.paas/app.yaml`: no `healthcheck` on node:alpine; `root:` if a subdir; secret **names** only
- [ ] Local `docker build` + smoke test pass (env unquoted; `/api/inngest`=401 ok)
- [ ] App live + verified on the free koyracloud URL
- [ ] Apex strategy chosen; host-redirects replicated + **verified no www/apex loop**
- [ ] Email (MX/SPF/DKIM/DMARC/verification TXTs) preserved across the DNS move
- [ ] Custom domain serves from koyracloud (`server: cloudflare`, no `x-vercel`)
- [ ] Vercel project deleted (only after the domain is verified on koyracloud)
