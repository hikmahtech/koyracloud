// Async blog source: Payload (posts_koyracloud) first, local POSTS fill the rest.
// PAYLOAD_URL unset => local POSTS returned untouched (identical to the old build).
import { POSTS } from "./index.js";

const TIMEOUT_MS = 8000;

// Map a Payload doc to the site's post shape. Returns null when unusable.
// Like the a2-content js-index importer, the site shows a single `tag` (tags[0]).
export function mapPayloadDoc(d) {
  if (!d || typeof d.title !== "string" || typeof d.slug !== "string" || typeof d.body !== "string") return null;
  if (!/^[a-z0-9][a-z0-9-]*$/i.test(d.slug)) return null;
  const tags = Array.isArray(d.tags)
    ? d.tags.map((t) => (typeof t === "string" ? t : t && (t.tag || t.name))).filter(Boolean)
    : [];
  const post = {
    slug: d.slug,
    title: d.title,
    description: typeof d.description === "string" ? d.description : "",
    date: typeof d.date === "string" ? d.date.slice(0, 10) : "",
    tag: tags[0] || "",
    body: d.body,
  };
  if (typeof d.author === "string" && d.author) post.author = d.author;
  if (typeof d.updated === "string" && d.updated) post.updated = d.updated.slice(0, 10);
  if (Array.isArray(d.faq)) {
    const faq = d.faq.filter((f) => f && typeof f.question === "string" && typeof f.answer === "string");
    if (faq.length) post.faq = faq;
  }
  if (d.cover) post.cover = typeof d.cover === "string" ? d.cover : d.cover.url || undefined;
  if (d.investigation) post.investigation = d.investigation;
  return post;
}

// Payload wins on slug; local fills the rest; newest first.
export function mergePosts(payloadPosts, local) {
  const bySlug = new Map(local.map((p) => [p.slug, p]));
  for (const p of payloadPosts) bySlug.set(p.slug, p);
  return [...bySlug.values()].sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

// Returns { posts, fromPayload }.
export async function loadPosts({ env = process.env, fetchImpl = globalThis.fetch, local = POSTS } = {}) {
  const base = (env.PAYLOAD_URL || "").replace(/\/+$/, "");
  if (!base) return { posts: local, fromPayload: false };
  try {
    const url = `${base}/api/posts_koyracloud?where[_status][equals]=published&limit=200&depth=1`;
    const res = await fetchImpl(url, { signal: AbortSignal.timeout(TIMEOUT_MS), headers: { accept: "application/json" } });
    if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const docs = Array.isArray(json.docs) ? json.docs : [];
    const mapped = docs
      .filter((d) => !d._status || d._status === "published")
      .map(mapPayloadDoc)
      .filter(Boolean);
    if (!mapped.length) return { posts: local, fromPayload: false };
    return { posts: mergePosts(mapped, local), fromPayload: mapped.length > 0 };
  } catch (e) {
    console.warn(`[blog] Payload unavailable, using local posts: ${e.message}`);
    return { posts: local, fromPayload: false };
  }
}
