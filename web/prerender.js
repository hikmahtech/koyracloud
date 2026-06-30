// Post-build prerenderer. Takes the SPA shell Vite produced (dist/index.html)
// and the SSR bundle (dist-server/entry-server.js), and writes a fully-rendered
// static HTML file per public route — real content + correct <head> — so crawlers
// and AI agents get server-side HTML with no JavaScript required.
//
// Run by `npm run build` after `vite build` and `vite build --ssr`.
import { readFileSync, writeFileSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const dist = join(__dirname, "dist");

const { render, getRoutes, POSTS } = await import("./dist-server/entry-server.js");

const SITE = "https://koyracloud.com";
const escXml = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// The pristine SPA shell, read once and used as the template for every route.
const template = readFileSync(join(dist, "index.html"), "utf-8");

const escAttr = (s) => String(s).replace(/"/g, "&quot;");
// Escape `<` in JSON-LD so a literal "</script>" in data can't break out of the tag.
const escJson = (obj) => JSON.stringify(obj).replace(/</g, "\\u003c");

function setTitle(html, v) {
  return html.replace(/<title>[\s\S]*?<\/title>/, `<title>${v}</title>`);
}
function setAttrContent(html, sel, value) {
  // sel like 'name="description"' or 'property="og:title"'. Replaces the content="" of the matching meta.
  const re = new RegExp(`(<meta\\s+${sel}\\s+content=")[^"]*(")`, "i");
  return html.replace(re, `$1${escAttr(value)}$2`);
}
function setCanonical(html, href) {
  return html.replace(/(<link\s+rel="canonical"\s+href=")[^"]*(")/i, `$1${escAttr(href)}$2`);
}
function injectJsonLd(html, blocks) {
  const tags = (Array.isArray(blocks) ? blocks : [blocks])
    .map((b) => `    <script type="application/ld+json">${escJson(b)}</script>\n  `)
    .join("");
  return html.replace("</head>", tags + "</head>");
}

function buildHtml(route, appHtml) {
  let html = template;
  html = setTitle(html, route.title);
  html = setAttrContent(html, 'name="description"', route.description);
  html = setAttrContent(html, 'property="og:title"', route.title);
  html = setAttrContent(html, 'property="og:description"', route.description);
  html = setAttrContent(html, 'property="og:url"', route.canonical);
  html = setAttrContent(html, 'name="twitter:title"', route.title);
  html = setAttrContent(html, 'name="twitter:description"', route.description);
  html = setCanonical(html, route.canonical);
  if (route.jsonLd) html = injectJsonLd(html, route.jsonLd);
  html = html.replace('<div id="root"></div>', `<div id="root">${appHtml}</div>`);
  return html;
}

function outPath(routePath) {
  if (routePath === "/") return join(dist, "index.html");
  return join(dist, routePath, "index.html");
}

const routes = getRoutes();
for (const route of routes) {
  const appHtml = render(route.path);
  const html = buildHtml(route, appHtml);
  const out = outPath(route.path);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, html);
  console.log(`prerendered ${route.path} -> ${out.replace(dist, "dist")}`);
}

// sitemap.xml — generated from the same routes the prerenderer just wrote, so a
// new post is in the sitemap automatically (no hand-maintained list to drift).
const dateBySlug = Object.fromEntries(POSTS.map((p) => [p.slug, p.date]));
const sitemap =
  `<?xml version="1.0" encoding="UTF-8"?>\n` +
  `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
  routes
    .map((r) => {
      const slug = r.path.startsWith("/blog/") ? r.path.slice(6) : null;
      const lastmod = slug && dateBySlug[slug] ? `\n    <lastmod>${dateBySlug[slug]}</lastmod>` : "";
      const priority = r.path === "/" ? "1.0" : r.path === "/docs" ? "0.9" : slug ? "0.8" : "0.7";
      return `  <url>\n    <loc>${r.canonical}</loc>${lastmod}\n    <changefreq>${slug ? "monthly" : "weekly"}</changefreq>\n    <priority>${priority}</priority>\n  </url>`;
    })
    .join("\n") +
  `\n</urlset>\n`;
writeFileSync(join(dist, "sitemap.xml"), sitemap);
console.log(`wrote sitemap.xml (${routes.length} urls)`);

// blog/rss.xml — POSTS is already newest-first.
const rss =
  `<?xml version="1.0" encoding="UTF-8"?>\n` +
  `<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n  <channel>\n` +
  `    <title>koyracloud blog</title>\n` +
  `    <link>${SITE}/blog</link>\n` +
  `    <atom:link href="${SITE}/blog/rss.xml" rel="self" type="application/rss+xml" />\n` +
  `    <description>Self-hosting a PaaS on Docker Swarm — push-to-deploy, custom domains, workers, and moving off Vercel and Heroku onto your own hardware.</description>\n` +
  `    <language>en</language>\n` +
  POSTS.map((p) =>
    `    <item>\n` +
    `      <title>${escXml(p.title)}</title>\n` +
    `      <link>${SITE}/blog/${p.slug}</link>\n` +
    `      <guid>${SITE}/blog/${p.slug}</guid>\n` +
    `      <pubDate>${new Date(p.date).toUTCString()}</pubDate>\n` +
    `      <description>${escXml(p.description)}</description>\n` +
    `    </item>`,
  ).join("\n") +
  `\n  </channel>\n</rss>\n`;
mkdirSync(join(dist, "blog"), { recursive: true });
writeFileSync(join(dist, "blog", "rss.xml"), rss);
console.log(`wrote blog/rss.xml (${POSTS.length} items)`);

// The SSR bundle is a build artifact, not something to ship in the image.
rmSync(join(__dirname, "dist-server"), { recursive: true, force: true });
console.log(`prerendered ${routes.length} routes`);
