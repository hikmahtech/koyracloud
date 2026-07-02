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

For the exact minimum permissions each credential needs (Docker socket, NFS,
registry, GitHub OAuth scopes), see [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md).

## Handling secrets

App secrets are encrypted at rest (Fernet) and injected at deploy. The Fernet master
key, session secret, OAuth client secret and clone token are Docker secrets — never
commit them. `.env`/`deploy/koyracloud.env` are gitignored.
