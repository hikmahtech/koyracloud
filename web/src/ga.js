// Google Analytics 4 — loaded only when the instance is configured with a
// Measurement ID (served at runtime via /api/config → ga_measurement_id). This
// keeps GA OFF by default, so a self-hosted koyracloud never ships analytics or
// inherits the official site's property; only an operator who sets
// KOYRA_GA_MEASUREMENT_ID turns it on.
let initialized = false;

export function initGA(measurementId) {
  if (!measurementId || initialized) return;
  initialized = true;

  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${measurementId}`;
  document.head.appendChild(s);

  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag("js", new Date());
  window.gtag("config", measurementId);

  // SPA route changes don't reload the page, so send a page_view manually.
  const send = () => window.gtag("event", "page_view", {
    page_path: location.pathname + location.search,
    page_location: location.href,
  });
  const wrap = (method) => {
    const orig = history[method];
    history[method] = function () { const r = orig.apply(this, arguments); send(); return r; };
  };
  wrap("pushState");
  wrap("replaceState");
  window.addEventListener("popstate", send);
}
