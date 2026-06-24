## Custom Domains and Automatic HTTPS, the Boring Way

Every app on koyracloud gets a platform subdomain out of the box: `myapp-abc123.apps.example.com`. It works. It's HTTPS. The certificate renews itself and you never think about it again. That's the dream, and it's real.

But if you want your users to visit `app.yourcompany.com` instead, there's no friction. Point two DNS records at the edge, and the cert appears automatically. The edge renews it. You forget about it. That's what "boring infrastructure" means—the technology becomes invisible because it works.

## Two Tiers: Platform Subdomains and Custom Domains

**Platform subdomains** are automatic. When you deploy an app, koyracloud assigns it a subdomain of the platform's base domain (`apps.example.com`, by convention). Traefik—the edge ingress controller—handles all the HTTP routing and HTTPS termination. Let's Encrypt mints the certificate via ACME, and a cert resolver renews it before expiry. You don't touch DNS. You don't wire up anything. The cert just exists, valid and renewed, forever.

This is enough for internal tools, staging, or quick demos. But if you own a domain—your company domain, a brand, a public API—you want to use it. That's what custom domains do.

**Custom domains** use Cloudflare for SaaS, the same system Vercel uses. You control the domain; Cloudflare controls the edge certificate. The flow is:

1. In the koyracloud dashboard, go to your app's Domains tab.
2. Add your custom domain (e.g., `api.acme-corp.com`).
3. Copy two CNAME records and add them at your domain registrar.
4. Cloudflare provisions and manages the certificate.

That's it. No certbot cron job on your server. No "cert expired, everything's down" pages at 2am. No Kubernetes secret with a PEM file you have to rotate. The edge mints the cert, the edge renews it. The edge is Cloudflare, which has teams of people thinking about certificate validity and chain trust. You don't.

## Why This Matters: The Before Times

If you've ever renewed a TLS certificate manually, you know the tedium. Install certbot. Set up a cron job. Point a domain at the server. Wait for the ACME challenge to validate. If the DNS is slow or the cron is misconfigured, the cert expires and your site goes down. Debugging the cron logs at midnight becomes a skill you don't want.

Then you add a second domain. Then a third. Each one is another cron invocation, another renewal window to track, another thing that can drift.

Kubernetes simplified this with cert-manager, but you still need to maintain the cert-manager controller, understand CertificateRequest objects, debug ACME provider integrations, and rotate secrets. It's less manual, but it's not invisible.

The insight behind "the edge mints and renews it" is that you don't need the certificate machinery running on your own infrastructure at all. Let the edge handle it. Traefik handles platform subdomains because it's already your edge. Cloudflare handles custom domains because it's Cloudflare's edge. Neither requires anything on your side except pointing a DNS record and waiting a few minutes.

## Choosing a Primary Domain

An app can have multiple domains. You pick one as the primary. This matters for a few things: the dashboard displays it first, redirects might use it, and some integrations (like webhooks or OAuth callbacks) often reference it.

Switching the primary domain is one click. Removing a domain is instant. Adding another is just two more CNAME records. You're not baking domains into config files or redeploying the app.

## The Apex Domain Wrinkle

There's one gotcha worth knowing about, though it's not actually a blocker: bare domains (a root domain like `acme-corp.com` instead of `api.acme-corp.com`) can't be CNAME records under old DNS rules. An apex domain's A record has to point to an IP.

Cloudflare for SaaS handles this with CNAME flattening: you point the apex to Cloudflare's CNAME, and Cloudflare flattens it at the nameserver level so the A record lookup still works. It's a bit of DNS sorcery, but it works. koyracloud's documentation covers the apex-domain setup and some alternatives (like using a `www.` subdomain as the primary, which avoids the issue entirely). The point: apex domains are solvable, not a dead end.

## A Concrete Example

Here's what it looks like in practice:

```
App: my-api
Platform subdomain: my-api-xyz.apps.example.com → works, cert valid
Custom domain: api.acme-corp.com → add two CNAMEs:

  _acme-challenge.api.acme-corp.com  CNAME  ...cloudflare-validation-url...
  api.acme-corp.com                  CNAME  ...cloudflare-edge...
```

Wait 5 minutes for DNS propagation. Cloudflare provisions the cert. You visit `https://api.acme-corp.com`. It loads. The certificate is valid. You never touch it again.

## Single-Operator Reality Check

This is a self-hosted PaaS. Traefik is your edge (plus Cloudflare's edge for custom domains). You're not getting a global CDN with 300 edge locations. You're getting a single Traefik instance, probably in the same data center as your apps, routing traffic and terminating TLS. That's plenty for internal tools, small teams, or regional deployments. Just know what you have.

But what you do have is the TLS story of a much bigger platform: certificates that materialize, renew themselves, and never break in the middle of the night. That part isn't an open-source fantasy. It's the only way modern infrastructure should work.

See the [custom domains guide](https://github.com/hikmahtech/koyracloud) or the `docs/` folder in the GitHub repo for setup details.
