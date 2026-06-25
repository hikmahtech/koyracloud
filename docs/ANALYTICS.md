# Analytics & search indexing

koyracloud.com reuses the same Google account and tooling as the other Hikmah
sites (e.g. domainposture.com): one read-only analytics CLI, IndexNow for
automated submission, GA4 for traffic, and Search Console for indexing.

## Reading traffic & search data — `hikmah-analytics-toolkit`

The account-wide, read-only CLI at `~/Workspace/hikmah/analytics-toolkit` already
covers **every** property `arshad@hikmahtechnologies.com` can see — no per-site
setup. Once koyracloud.com is added as a GA4 property and a GSC site (below), it
shows up there automatically:

```bash
cd ~/Workspace/hikmah/analytics-toolkit
node discover.mjs                              # list every GA4 property + GSC site
node gsc.mjs sc-domain:koyracloud.com          # Search Console: clicks, impressions, queries, pages
node ga.mjs properties/<id>                     # GA4 traffic report
```

Auth is shared (`~/.config/hikmah-analytics/`); if a token has expired, re-run the
toolkit's `login.sh` once. Nothing about koyracloud needs to change for reads.

## Automated submission — IndexNow (Bing, Yandex, Seznam, Naver)

IndexNow is the only fully-automated "tell the engines I changed" mechanism left
(Google retired anonymous sitemap pinging in 2023). The key file is committed at
`web/public/64884bd0fe3b93765f92057d88b05222.txt`, served at
`https://koyracloud.com/64884bd0fe3b93765f92057d88b05222.txt`.

```bash
cd web
INDEXNOW_KEY=64884bd0fe3b93765f92057d88b05222 npm run seo:indexnow            # submit all sitemap URLs
INDEXNOW_KEY=64884bd0fe3b93765f92057d88b05222 npm run seo:indexnow -- --dry-run
INDEXNOW_KEY=64884bd0fe3b93765f92057d88b05222 npm run seo:indexnow -- <url>...  # only specific URLs
```

One POST fans out to every participating engine. Run it after publishing or
changing posts. `INDEXNOW_KEY` must equal the committed key file's basename.

## GA4

The control plane bakes a GA4 gtag into `index.html` at build time only when
`KOYRA_GA_MEASUREMENT_ID` is set (unset => no analytics, the self-host default).
CI passes it from the `KOYRA_GA_MEASUREMENT_ID` repository secret
(`.github/workflows/ci.yml`, build job). To enable on koyracloud.com:

1. In GA4, create a property + Web data stream for `https://koyracloud.com` → copy the `G-XXXXXXXXXX` measurement ID.
2. Add it as a GitHub Actions **secret** named `KOYRA_GA_MEASUREMENT_ID`.
3. Re-run the deploy (push to `main`) — the gtag is then in the served HTML.

## One-time console steps (manual — needs your Google/Bing login)

These can't be scripted with the read-only toolkit:

1. **Google Search Console** → add `koyracloud.com` (Domain property, DNS TXT verification via Cloudflare) → **Sitemaps** → submit `sitemap.xml`.
2. **Google** per-URL "Request Indexing" (URL Inspection) for a few priority pages — not API-accessible, optional accelerant.
3. **Bing Webmaster Tools** → add `koyracloud.com` (can import from the verified GSC property). The IndexNow key is auto-recognized once Bing sees the site.
