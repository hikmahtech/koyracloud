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

const { render, getRoutes } = await import("./dist-server/entry-server.js");

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

// The SSR bundle is a build artifact, not something to ship in the image.
rmSync(join(__dirname, "dist-server"), { recursive: true, force: true });
console.log(`prerendered ${routes.length} routes`);
