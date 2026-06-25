#!/usr/bin/env node
// Notify IndexNow-participating engines (Bing, Yandex, Seznam, Naver) that
// koyracloud.com URLs have changed. IndexNow is the only fully-automated submit
// mechanism left — Google retired anonymous sitemap pinging in 2023 and Bing
// folded its ping into IndexNow. Google still needs Search Console (manual; see
// docs/ANALYTICS.md). Ported from the domainposture.com toolkit.
//
// How it works: a public key file lives at `${base}/${INDEXNOW_KEY}.txt` and
// contains the key verbatim. We POST the key + URL list to one IndexNow endpoint,
// which fans the notification out to every participating engine.
//
// Usage:
//   INDEXNOW_KEY=<key> node scripts/indexnow-submit.mjs            # submit every sitemap URL
//   INDEXNOW_KEY=<key> node scripts/indexnow-submit.mjs --dry-run  # print, don't POST
//   INDEXNOW_KEY=<key> node scripts/indexnow-submit.mjs <url>...   # submit only these URLs
//
// INDEXNOW_KEY must equal the basename of the committed public/<key>.txt file.
// Exit codes: 0 — accepted · 1 — submission failed · 2 — usage/config error.

const ENDPOINT = "https://api.indexnow.org/indexnow";
const MAX_URLS_PER_REQUEST = 10_000;
const base = () => process.env.SITE_URL ?? "https://koyracloud.com";

function resolveOrigin(urlList) {
  const origins = new Set(urlList.map((u) => new URL(u).origin));
  if (origins.size > 1) {
    throw new Error(`URLs span multiple origins, IndexNow needs one: ${[...origins].join(", ")}`);
  }
  return [...origins][0];
}

async function urlsFromSitemap() {
  const sitemapUrl = `${base()}/sitemap.xml`;
  const res = await fetch(sitemapUrl);
  if (!res.ok) throw new Error(`Could not fetch ${sitemapUrl}: ${res.status} ${res.statusText}`);
  const xml = await res.text();
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1].trim());
  if (locs.length === 0) throw new Error(`No <loc> entries found in ${sitemapUrl}`);
  return locs;
}

const chunk = (items, size) => {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
};

async function submit(key, urlList, dryRun) {
  const origin = resolveOrigin(urlList);
  const host = new URL(origin).host;
  const keyLocation = `${origin}/${key}.txt`;
  const batches = chunk(urlList, MAX_URLS_PER_REQUEST);

  for (const [index, batch] of batches.entries()) {
    if (dryRun) {
      console.log(`[dry-run] batch ${index + 1}/${batches.length} → ${batch.length} URLs`);
      for (const url of batch) console.log(`  ${url}`);
      continue;
    }
    const res = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ host, key, keyLocation, urlList: batch }),
    });
    // 200 OK and 202 Accepted both mean success; 202 is "key validation pending".
    if (res.status !== 200 && res.status !== 202) {
      const text = await res.text().catch(() => "");
      throw new Error(
        `IndexNow rejected batch ${index + 1}/${batches.length}: ${res.status} ${res.statusText} ${text}`.trim(),
      );
    }
    console.log(`Submitted batch ${index + 1}/${batches.length} (${batch.length} URLs) → ${res.status} ${res.statusText}`);
  }
}

async function main() {
  const key = process.env.INDEXNOW_KEY;
  if (!key) {
    console.error("INDEXNOW_KEY is not set. It must equal the basename of public/<key>.txt (the committed key file).");
    process.exit(2);
  }
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const explicitUrls = args.filter((a) => !a.startsWith("--"));
  const urlList = explicitUrls.length > 0 ? explicitUrls : await urlsFromSitemap();
  console.log(`IndexNow → ${resolveOrigin(urlList)} · key ${key.slice(0, 6)}… · ${urlList.length} URL(s)${dryRun ? " (dry-run)" : ""}`);
  await submit(key, urlList, dryRun);
  console.log(dryRun ? "Dry run complete — nothing submitted." : "Done.");
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
