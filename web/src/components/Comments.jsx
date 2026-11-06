import { useEffect, useRef } from "react";

const BASE = "https://comments.hikmahtech.in";

function loadOnce(tag, attrs) {
  const key = attrs.href || attrs.src;
  const existing = document.querySelector(`[data-artalk="${key}"]`);
  if (existing) return existing.__p || Promise.resolve();
  const el = document.createElement(tag);
  Object.assign(el, attrs);
  el.setAttribute("data-artalk", key);
  el.__p = new Promise((res, rej) => { el.onload = res; el.onerror = rej; });
  document.head.appendChild(el);
  return el.__p;
}

// Lazy Artalk widget: loads CSS/JS only when scrolled near. pageKey is the
// canonical post URL and must never change.
export default function Comments({ pageKey, pageTitle }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let artalk = null;
    let dead = false;
    const start = async () => {
      try {
        await Promise.all([
          loadOnce("link", { rel: "stylesheet", href: `${BASE}/dist/Artalk.css` }),
          loadOnce("script", { src: `${BASE}/dist/Artalk.js`, async: true }),
        ]);
        if (dead || !window.Artalk) return;
        artalk = window.Artalk.init({ el, server: BASE, site: "koyracloud", pageKey, pageTitle });
      } catch {
        /* comments are optional */
      }
    };
    let io = null;
    if (typeof IntersectionObserver === "undefined") start();
    else {
      io = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) { io.disconnect(); start(); }
      }, { rootMargin: "200px" });
      io.observe(el);
    }
    return () => { dead = true; io?.disconnect(); artalk?.destroy?.(); };
  }, [pageKey, pageTitle]);
  return <div ref={ref} className="mt-10" />;
}
