import { describe, it, expect, vi } from "vitest";
import { loadPosts, mapPayloadDoc } from "./source.js";

const local = [
  { slug: "a", title: "A", description: "d", date: "2026-01-01", tag: "T", body: "x" },
  { slug: "b", title: "B", description: "d", date: "2026-03-01", tag: "T", body: "x" },
];
const doc = (o) => ({ title: "P", slug: "p", body: "hi", date: "2026-02-02T00:00:00Z", _status: "published", ...o });
const ok = (docs) => vi.fn(async () => ({ status: 200, json: async () => ({ docs }) }));
const env = { PAYLOAD_URL: "https://cms.test" };

describe("loadPosts", () => {
  it("unset: local unchanged, no fetch", async () => {
    const f = vi.fn();
    const r = await loadPosts({ env: {}, fetchImpl: f, local });
    expect(r.posts).toBe(local);
    expect(f).not.toHaveBeenCalled();
  });
  it("falls back on 500, network error and timeout", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const f of [
      async () => ({ status: 500 }),
      async () => { throw new Error("ECONNREFUSED"); },
      async () => { throw new DOMException("t", "TimeoutError"); },
    ]) {
      expect((await loadPosts({ env, fetchImpl: f, local })).posts).toBe(local);
    }
  });
  it("payload wins by slug, local fills, newest first, optional fields tolerated", async () => {
    const r = await loadPosts({ env, fetchImpl: ok([doc({ slug: "a", title: "A2" }), doc({})]), local });
    expect(r.posts.map((p) => p.slug)).toEqual(["b", "a", "p"]);
    expect(r.posts.find((p) => p.slug === "a").title).toBe("A2");
    const p = r.posts.find((x) => x.slug === "p");
    expect(p.tag).toBe("");
    expect(p.date).toBe("2026-02-02");
  });
  it("drops drafts", async () => {
    const r = await loadPosts({ env, fetchImpl: ok([doc({ _status: "draft" })]), local });
    expect(r.posts).toEqual(local);
  });
});

describe("mapPayloadDoc", () => {
  it("maps extras and tag=tags[0]", () => {
    const p = mapPayloadDoc(doc({ tags: ["x", "y"], author: "Z", updated: "2026-05-05T01:00", faq: [{ question: "q", answer: "a" }], cover: { url: "https://i/x.png" }, investigation: "i" }));
    expect(p).toMatchObject({ tag: "x", author: "Z", updated: "2026-05-05", faq: [{ question: "q", answer: "a" }], cover: "https://i/x.png", investigation: "i" });
  });
  it("rejects bad slug / missing body", () => {
    expect(mapPayloadDoc(doc({ slug: "../x" }))).toBeNull();
    expect(mapPayloadDoc(doc({ body: undefined }))).toBeNull();
  });
});
