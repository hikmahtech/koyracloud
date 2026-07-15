# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Use GitHub's **Report a vulnerability** (Security → Advisories), or
- email **arshad@hikmahtechnologies.com**.

Include reproduction steps and impact. You'll get an acknowledgement within a few
days, and we'll coordinate a fix and disclosure timeline with you.

## Scope & threat model

koyracloud is a **single-operator** platform for **trusted code**. By design:

- The control plane mounts the host's Docker socket on a manager node — it is
  root-equivalent on the cluster. This is acceptable only because access is gated
  by a GitHub OAuth allowlist and the deployed code is trusted.
- It is **not** hardened for multi-tenant or untrusted-code use. Do not expose app
  creation to people you don't trust to run code on your swarm.

Reports about the trusted-operator model itself (e.g. "the socket is powerful") are
known and out of scope. Reports about breaking *out* of the intended access controls
(auth bypass, secret exposure, SSRF, injection, path traversal, etc.) are in scope
and appreciated.

See [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md) for exactly what each credential the
control plane uses is scoped to and why.

## Handling secrets

App secrets are encrypted at rest (Fernet) and injected at deploy. Everything
sensitive the instance itself needs — the Fernet master key, session secret, webhook
secret, Redis admin password, OAuth client secret, clone token, Resend key and
Cloudflare token (eight in all, see `deploy/README.md` §5) — is a Docker secret —
never commit them. `.env`/`deploy/koyracloud.env` are gitignored.

## The internal registry port

The built-in image registry is published on the Swarm ingress mesh, so port **5000
answers on every node's public interface, unauthenticated** (that's how each node
pulls app images as `127.0.0.1:5000`). Firewall port 5000 from anything outside the
swarm — an exposed registry allows image pull/push/delete by anyone who can reach it.
