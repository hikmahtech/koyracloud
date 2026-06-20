# koyracloud email per domain — full mailboxes + transactional, on an isolated mail node

**Status:** design · **parked** pending deliverability validation (reverse DNS) · 2026-06-20
**Scope:** decomposed into three sub-projects (P1 → P2 → P3), each gets its own spec → plan → build
**Note:** operator-specific values (public IPs, ISP, host names, internal addressing) are
intentionally **not** in this public doc — they live in the operator's private notes. This
doc is the generic, open-source design + status record.

## Problem

A koyracloud App today is a git repo → built image → HTTP service, with optional
[workers, cron, and a shared Redis bus](2026-06-16-background-tasks-design.md). There is **no
email**: an app can't give its domain real mailboxes (`you@yourdomain.com`), and it can't send
transactional mail (password resets, receipts) *from* its own domain with good deliverability.
The big PaaS platforms don't offer this at all — so it's a genuine differentiator, and because
koyracloud is self-hostable, an operator can opt into running it.

## Goal

For a domain that koyracloud serves, optionally provide:

- **Full mailboxes** — real accounts people log into: send + receive, IMAP/JMAP, webmail,
  spam filtering, storage.
- **Transactional sending** — hosted apps send mail *from* their domain through a platform
  primitive (apps stop carrying their own SMTP creds), kept **reputationally separate** from
  personal mailbox mail.

Email is an **opt-in component**: off by default; an operator enables it only if they have the
infrastructure for it (a public-IP host + the DNS/deliverability prerequisites below).

## Non-goals

- Not a transactional-email reseller; not "bring your own ESP" as the only mode (relaying via an
  external ESP is a documented *fallback*, not the design).
- The mail server does **not** run on the swarm (see Isolation).
- No groupware/calendaring ambitions in v1 (mailboxes + transactional only).
- koyracloud does not see apps' *internal* registered users — each app owns its own DB. "Mail"
  here means mailboxes on a domain, not an app's user list.

## Architecture

### One mail server on an isolated edge node ("Option A")

The mail server runs as a **single, self-contained service on a dedicated node that is not part
of the swarm**. The chosen stack is **Stalwart** — one memory-safe binary doing SMTP + IMAP/JMAP
+ spam filtering + DKIM + an admin API. It was chosen over Mailcow/Mailu because:

- it's **one service**, not a ~15-container compose stack that assumes it owns the host (those
  are hostile to Docker Swarm and far heavier);
- on an internet-facing box, **a smaller attack surface** (one hardened binary) matters more
  than Mailcow's extra features (webmail/groupware = more exposed surface we don't want);
- it runs comfortably on a small node.

**The control plane manages mail by reaching *in*:**

- **Provisioning** — when a domain/mailbox is created, the control plane calls the mail server's
  **admin API** to create the domain + mailbox and generate the per-domain DKIM key, then writes
  the DNS (MX/SPF/DKIM/DMARC/autoconfig).
- **Transactional send** — hosted apps submit to the mail server's submission endpoint with
  per-app/per-domain credentials the control plane issues; the server DKIM-signs and sends out.
- **Webmail** rides the existing Cloudflare tunnel via a connector **on the mail node** (an
  outbound-only dial-out), so there is **no inbound `80/443`**.
- **Backups** are pulled by the platform from the mail node, or pushed by the mail node to cloud
  object storage.

### Isolation model (why the mail node is off the swarm)

The mail node is the most-exposed surface in the system (public SMTP is attacked constantly). It
must be isolated such that **a full compromise of the mail node cannot pivot into the platform**.
Two rules make that real:

1. **Not a swarm member.** No overlay networks, no access to internal service VIPs, no Docker
   socket. (The control plane mounts the Docker socket — root over the cluster — so this matters.)
2. **A directional firewall**, enforced *off the box* (at the network, not on the host — a
   root-compromised host can't be trusted to police itself):

   | Direction | Policy |
   |---|---|
   | platform → mail node (provisioning, submission) | **allow** |
   | mail node → platform (new connections) | **block** |
   | mail node → internet (send, ACME, updates) | allow |
   | internet → mail node (the mail ports only) | allow (port-forward) |

   Because the platform only ever *initiates into* the mail node — never the reverse — there are
   **zero inbound pinholes** from the mail node into the platform. That's the property "Option A"
   buys, and why mailboxes live on the edge node rather than on a swarm-side backend (a swarm-side
   backend would force a `mail-node → platform` hole, re-opening the isolation).

**Self-host isolation profiles** (documented for operators; pick one):

- **On-prem + VLAN** — dedicated VLAN for the mail node, inter-VLAN ACL as above. Recommended
  default where a managed switch/router is available.
- **On-prem + host-firewall only** — strict default-deny + egress lock on the mail node. Simpler
  (pure host config), but weaker: it only contains an *unprivileged* compromise, not a root one.
- **VPS + VPN** — mail node is a cloud host with a clean IP, joined back to the platform over a
  VPN. Strongest isolation + best deliverability; costs a VPS and puts mail data off-prem.

### Transactional separation (three layers)

Personal-mailbox mail and machine-sent app mail want **separate reputation** so a misbehaving
app can't poison mailbox deliverability:

1. **Day 1 — separate identity:** transactional sends from its own subdomain with its own DKIM
   selector + SPF + dedicated submission credentials + its own queue. Receivers weight
   DKIM-aligned *domain* reputation heavily, so this isolates most of the risk with no extra infra.
2. **Upgrade — separate egress IP:** route transactional out a second public IP with its own PTR,
   so an IP-reputation hit can't touch the mailbox IP. Add when volume justifies; no redesign.
3. **Escape hatch — external relay:** send transactional through a transactional ESP while
   mailboxes stay self-hosted, if you ever want zero deliverability risk on that channel.

## Deliverability prerequisites (the gate)

These block self-hosted mail far more often than the software does, and several are
ISP/DNS facts outside the code. **The project is parked until #2 is confirmed**, because it is the
go/no-go for *direct* self-hosted sending:

1. **Static public IP** for the mail node.
2. **PTR / reverse DNS** — the sending IP must reverse-resolve to the mail hostname, and the
   forward A record must match (forward-confirmed reverse DNS). **Only the ISP can set the PTR.**
   Without it, outbound is spam-foldered/rejected. (Receiving and webmail still work without it;
   if the ISP won't set it, fall back to an outbound relay.)
3. **SPF, DKIM, DMARC** for each sending domain (control plane writes these).
4. **ISP port 25** — must be open inbound (else MX can't receive) and outbound (else relay).
5. **Forward DNS** — the mail/MX hostnames must be **DNS-only (unproxied)** records — an HTTP
   proxy hides the IP and breaks SMTP. (This is the deliberate exception to koyracloud's normal
   proxied app records.)
6. **Egress pinning** — with multiple WANs, mail must egress deterministically from the IP whose
   PTR is set, or reverse-DNS matching flaps.

## Decomposition

- **P1 — the isolated mail node + infra wiring.** Provision a non-swarm host (base container
  runtime, no swarm join), deploy Stalwart, lock down the host/edge firewall, run the
  webmail tunnel connector. On the GitOps side this is a new non-swarm inventory group + a
  standalone deploy playbook + a `mail` role (kept out of the swarm site playbook). The inbound
  port-forwards and the PTR request are manual operator steps (router web-UIs + ISP).
- **P2 — control-plane mail integration.** A mail-provisioning client (talks the mail server's
  admin API), DNS automation for MX/SPF/DKIM/DMARC, the transactional submission path + per-app
  credential issuance, a manifest opt-in, and dashboard UI. This is the larger build.
- **P3 — open-source generalization + docs.** The three isolation profiles, the deliverability
  guide, and a self-host tutorial so an operator can stand the component up cleanly.

## Status — done vs remaining

**Done (reference deployment):**

- The isolated mail node is provisioned and is **not** a swarm member.
- The directional firewall (platform↔mail) is built and **verified**: the node is single-homed
  on its isolated segment, and mail-node → platform is blocked while platform → mail-node works.
- Capability checks passed: outbound `25` reaches public MX; the candidate IPs are clean on
  major block lists.
- The network/topology side is documented in the operator's private infrastructure repo.

**Remaining:**

1. **Deliverability validation (gating):** obtain the **PTR** from the ISP for the mailbox IP
   (and, for transactional separation, a second PTR for the transactional IP). This unparks
   the project.
2. **Inbound port-forwards** for the chosen mail ports (manual, router web-UIs).
3. **P1 build:** the mail role/playbook + Stalwart deploy + host firewall + webmail connector.
4. **P2 build:** the control-plane integration (provisioning, DNS automation, transactional
   submission, manifest + UI).
5. **P3:** generalize + document for self-hosters.

**Decisions locked:** Stalwart; Option A (full server on the edge node, control plane reaches in,
zero pinholes); webmail via tunnel (no inbound `80/443`, certs via DNS-01); native clients
supported (so inbound `25/465/587/993`); two-IP transactional separation; the three-layer
transactional plan.

## Open questions

- Whether the ISP will set the PTR (the gate). If not: adopt the outbound-relay fallback and
  decide whether the "fully self-hosted" story is still worth it for this operator.
- Multi-domain tenancy details in the control plane (per-tenant DKIM selectors, mailbox quotas).
- Backup target + retention for mailbox storage.
