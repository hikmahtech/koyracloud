import { Link } from "react-router-dom";
import { PublicNav, Footer } from "../components/Chrome.jsx";
import { POSTS, readingTime } from "../posts/index.js";
import { useSeo } from "../seo.js";

export default function Blog() {
  useSeo({
    title: "Blog — koyracloud",
    description:
      "Notes on self-hosting a PaaS on Docker Swarm: push-to-deploy, custom domains, background workers, and moving apps off Vercel and Heroku onto your own hardware.",
    canonical: "https://koyracloud.com/blog",
  });

  return (
    <div className="grid-bg min-h-screen">
      <PublicNav />
      <div className="max-w-3xl mx-auto px-6 py-16">
        <div className="eyebrow">Blog</div>
        <h1 className="font-display text-4xl mt-3 mb-3">Notes from the platform</h1>
        <p className="text-[var(--color-muted)] mb-10 leading-relaxed">
          Self-hosting, Docker Swarm, and the boring plumbing of shipping apps to your own hardware.
        </p>
        <div className="space-y-5">
          {POSTS.map((p) => (
            <Link key={p.slug} to={`/blog/${p.slug}`}
                  className="card p-7 block no-underline hover:border-[var(--color-line-strong)] transition">
              <div className="flex items-center gap-3 mb-3">
                <span className="mono text-xs text-acid border border-[var(--color-line)] rounded px-2 py-0.5">{p.tag}</span>
                <span className="mono text-xs text-[var(--color-muted)]">{p.date}</span>
                <span className="mono text-xs text-[var(--color-muted)]">· {readingTime(p.body)} min read</span>
              </div>
              <h2 className="font-display text-2xl mb-2 text-[var(--color-fg)]">{p.title}</h2>
              <p className="text-[var(--color-muted)] leading-relaxed">{p.description}</p>
              <span className="mono text-xs text-acid mt-4 inline-block">Read →</span>
            </Link>
          ))}
        </div>
      </div>
      <Footer />
    </div>
  );
}
