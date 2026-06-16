import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Inject a static Google Analytics 4 gtag into <head> at BUILD time, only when
// KOYRA_GA_MEASUREMENT_ID is set in the build env. Static (not JS-injected) so
// Search Console's "Google Analytics" verification — which reads the served
// HTML — can find it, and so GA loads without waiting on /api/config. Unset =>
// no tag in the HTML, so a self-hosted build ships no analytics by default.
function injectGA() {
  const id = process.env.KOYRA_GA_MEASUREMENT_ID || "";
  return {
    name: "inject-ga",
    transformIndexHtml(html) {
      if (!id) return html;
      const tag =
        `    <script async src="https://www.googletagmanager.com/gtag/js?id=${id}"></script>\n` +
        `    <script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}` +
        `gtag('js',new Date());gtag('config','${id}');</script>\n  `;
      return html.replace("</head>", tag + "</head>");
    },
  };
}

// Dev: proxy /api to the control plane on :8000. Prod: the control plane serves
// the built dist/ same-origin, so /api is already relative.
export default defineConfig({
  plugins: [react(), tailwindcss(), injectGA()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});
