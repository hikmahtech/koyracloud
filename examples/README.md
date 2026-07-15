# Example manifests

Runnable `.paas/app.yaml` starters — copy one into your repo's `.paas/` dir,
adjust `name`/`port`/commands, push, and deploy.

| Example | For |
|---------|-----|
| [`fastapi-react/`](fastapi-react/app.yaml) | A Python API that builds and serves a JS frontend (FastAPI + Vite, `runtime: python+node`) — build steps, predeploy migrations, persist dir, healthcheck, secrets. |
| [`static-site/`](static-site/app.yaml) | A static site with a build step (`runtime: static`) — Vite/Astro/Hugo/eleventy-style output served directly. A repo that's *just* `index.html` needs no manifest at all (zero-config static). |
| [`go-service/`](go-service/app.yaml) | A Go HTTP service (`runtime: go`) — two-stage build (`golang:1.23` → `distroless/static-debian12`), no `healthcheck`/`predeploy` (the runner has no shell or python3). |

Before pushing, lint your manifest against the exact rules the control plane uses —
no checkout required:

```bash
uvx --from "git+https://github.com/hikmahtech/koyracloud#subdirectory=control-plane" koyra validate
```

The full field reference lives in the in-app docs at `https://<your-instance>/docs`
(section "Manifest fields"). Common gotcha: `healthcheck:` probes with `python3`
*inside your container* — fine for generated runtimes, but a bring-your-own-Dockerfile
alpine image needs `python3` installed or the field omitted
(see [`docs/TROUBLESHOOTING.md`](../docs/TROUBLESHOOTING.md)). `runtime: go` can't use
`healthcheck:` (or `predeploy:`) at all — its distroless runner has neither a shell nor
python3.
