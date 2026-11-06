// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import Comments from "./Comments.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const URL_ = "https://koyracloud.com/blog/p";
let cb, init, root, host;

function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<Comments pageKey={URL_} pageTitle="P" />));
}
const scripts = () => document.querySelectorAll('script[src*="Artalk.js"]');

beforeEach(() => {
  init = vi.fn(() => ({ destroy() {} }));
  window.Artalk = { init };
  document.head.innerHTML = "";
  // auto-"load" appended resources
  const orig = document.head.appendChild.bind(document.head);
  document.head.appendChild = (el) => { orig(el); queueMicrotask(() => el.onload && el.onload()); return el; };
});
afterEach(() => { act(() => root.unmount()); host.remove(); delete globalThis.IntersectionObserver; });

describe("Comments", () => {
  it("injects nothing before intersection, once after, with canonical pageKey", async () => {
    globalThis.IntersectionObserver = class { constructor(f) { cb = f; } observe() {} disconnect() {} };
    mount();
    expect(scripts().length).toBe(0);
    await act(async () => { cb([{ isIntersecting: true }]); await new Promise((r) => setTimeout(r, 5)); });
    expect(scripts().length).toBe(1);
    expect(init).toHaveBeenCalledWith(expect.objectContaining({ server: "https://comments.hikmahtech.in", site: "koyracloud", pageKey: URL_ }));
  });
  it("loads immediately without IntersectionObserver", async () => {
    delete globalThis.IntersectionObserver;
    mount();
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
    expect(scripts().length).toBe(1);
    expect(init).toHaveBeenCalled();
  });
});
