import { useEffect } from "react";

// Client-side <head> management for the SPA: set title/description/canonical and
// an optional JSON-LD block per page, restoring the defaults on unmount.
// ponytail: client-side only — fine for Google's JS rendering; full prerender is
// the SEO phase's job, not this hook's.
function setMeta(name, value, attr = "name") {
  let el = document.head.querySelector(`meta[${attr}="${name}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, name);
    document.head.appendChild(el);
  }
  el.setAttribute("content", value);
}

function setCanonical(href) {
  let el = document.head.querySelector('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", "canonical");
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

export function useSeo({ title, description, canonical, jsonLd }) {
  useEffect(() => {
    const prevTitle = document.title;
    if (title) document.title = title;
    if (description) {
      setMeta("description", description);
      setMeta("og:title", title || prevTitle, "property");
      setMeta("og:description", description, "property");
      setMeta("twitter:title", title || prevTitle);
      setMeta("twitter:description", description);
    }
    if (canonical) {
      setCanonical(canonical);
      setMeta("og:url", canonical, "property");
    }
    let script;
    if (jsonLd) {
      script = document.createElement("script");
      script.type = "application/ld+json";
      script.text = JSON.stringify(jsonLd);
      document.head.appendChild(script);
    }
    return () => {
      document.title = prevTitle;
      if (script) script.remove();
    };
  }, [title, description, canonical, jsonLd]);
}
