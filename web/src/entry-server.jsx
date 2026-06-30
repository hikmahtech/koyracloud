// Server entry for build-time prerendering (browserless SSG). Vite SSR-builds
// this to dist-server/, then prerender.js calls render() + getRoutes() to write
// a real static HTML file per public route. The dynamic, auth-gated Dashboard is
// deliberately NOT prerendered — only the public, indexable pages are.
import { renderToString } from "react-dom/server";
import { StaticRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Landing from "./pages/Landing.jsx";
import Docs from "./pages/Docs.jsx";
import Blog from "./pages/Blog.jsx";
import BlogPost from "./pages/BlogPost.jsx";
import { POSTS } from "./posts/index.js";

// Re-exported so the prerenderer can build the sitemap + RSS feed from the same
// post list, instead of a hand-maintained sitemap that drifts when posts change.
export { POSTS };

const SITE = "https://koyracloud.com";
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

export function render(url) {
  return renderToString(
    <QueryClientProvider client={queryClient}>
      <StaticRouter location={url}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/docs" element={<Docs />} />
          <Route path="/blog" element={<Blog />} />
          <Route path="/blog/:slug" element={<BlogPost />} />
        </Routes>
      </StaticRouter>
    </QueryClientProvider>
  );
}

// Per-route <head> data the prerenderer injects into the static HTML, so crawlers
// and AI agents see correct titles/descriptions/canonicals/structured data without
// running JavaScript.
export function getRoutes() {
  const staticRoutes = [
    {
      path: "/",
      title: "koyracloud — your own Vercel, self-hosted",
      description:
        "Open-source, self-hosted PaaS for your Docker Swarm. Connect a git repo with a small manifest — it builds a container image, runs it behind HTTPS, and handles secrets, domains, workers and cron.",
      canonical: `${SITE}/`,
    },
    {
      path: "/docs",
      title: "Docs — koyracloud",
      description:
        "How to deploy on koyracloud: the .paas/app.yaml manifest, runtimes, build and start commands, secrets, persistent storage, custom domains, workers and cron.",
      canonical: `${SITE}/docs`,
    },
    {
      path: "/blog",
      title: "Blog — koyracloud",
      description:
        "Notes on self-hosting a PaaS on Docker Swarm: push-to-deploy, custom domains, background workers, and moving apps off Vercel and Heroku onto your own hardware.",
      canonical: `${SITE}/blog`,
      jsonLd: {
        "@context": "https://schema.org",
        "@type": "Blog",
        name: "koyracloud blog",
        url: `${SITE}/blog`,
        description:
          "Self-hosting, Docker Swarm, and the boring plumbing of shipping apps to your own hardware.",
        blogPost: POSTS.map((p) => ({
          "@type": "BlogPosting",
          headline: p.title,
          description: p.description,
          datePublished: p.date,
          url: `${SITE}/blog/${p.slug}`,
        })),
      },
    },
  ];

  const postRoutes = POSTS.map((p) => ({
    path: `/blog/${p.slug}`,
    title: `${p.title} — koyracloud`,
    description: p.description,
    canonical: `${SITE}/blog/${p.slug}`,
    jsonLd: [
      {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        headline: p.title,
        description: p.description,
        datePublished: p.date,
        dateModified: p.date,
        author: { "@type": "Organization", name: "Hikmah Technologies", url: "https://hikmahtechnologies.com" },
        publisher: { "@type": "Organization", name: "koyracloud", url: SITE },
        mainEntityOfPage: `${SITE}/blog/${p.slug}`,
        url: `${SITE}/blog/${p.slug}`,
        inLanguage: "en",
      },
      {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: `${SITE}/` },
          { "@type": "ListItem", position: 2, name: "Blog", item: `${SITE}/blog` },
          { "@type": "ListItem", position: 3, name: p.title, item: `${SITE}/blog/${p.slug}` },
        ],
      },
    ],
  }));

  return [...staticRoutes, ...postRoutes];
}
