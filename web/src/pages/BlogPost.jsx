import { Link, useParams } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PublicNav, Footer } from "../components/Chrome.jsx";
import { getPost, readingTime } from "../posts/index.js";
import { useSeo } from "../seo.js";

const SITE = "https://koyracloud.com";

export default function BlogPost() {
  const { slug } = useParams();
  const post = getPost(slug);

  if (!post) {
    return (
      <div className="grid-bg min-h-screen">
        <PublicNav />
        <div className="max-w-3xl mx-auto px-6 py-24 text-center">
          <h1 className="font-display text-3xl mb-4">Post not found</h1>
          <Link to="/blog" className="text-acid no-underline hover:underline">← Back to the blog</Link>
        </div>
        <Footer />
      </div>
    );
  }

  const url = `${SITE}/blog/${post.slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: post.title,
    description: post.description,
    datePublished: post.date,
    dateModified: post.date,
    author: { "@type": "Organization", name: "Hikmah Technologies", url: "https://hikmahtechnologies.com" },
    publisher: { "@type": "Organization", name: "koyracloud" },
    mainEntityOfPage: url,
    url,
  };

  return (
    <div className="grid-bg min-h-screen">
      <PublicNav />
      <SeoHead post={post} url={url} jsonLd={jsonLd} />
      <article className="max-w-3xl mx-auto px-6 py-16">
        <Link to="/blog" className="mono text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">
          ← Blog
        </Link>
        <div className="flex items-center gap-3 mt-6 mb-4">
          <span className="mono text-xs text-acid border border-[var(--color-line)] rounded px-2 py-0.5">{post.tag}</span>
          <span className="mono text-xs text-[var(--color-muted)]">{post.date}</span>
          <span className="mono text-xs text-[var(--color-muted)]">· {readingTime(post.body)} min read</span>
        </div>
        <h1 className="font-display text-4xl leading-tight mb-8">{post.title}</h1>
        <div className="prose">
          <Markdown remarkPlugins={[remarkGfm]}>{post.body}</Markdown>
        </div>
        <PostFooter />
        <Link to="/blog" className="text-acid no-underline hover:underline mono text-xs">← All posts</Link>
      </article>
      <Footer />
    </div>
  );
}

// Per-post conversion footer: the "if you liked this, star the repo" nudge that
// turns a shared post into a GitHub star, plus the Hikmah byline for brand reach.
function PostFooter() {
  return (
    <div className="mt-14 mb-10">
      <div className="card p-7">
        <div className="font-display text-xl mb-1.5">koyracloud is open source</div>
        <p className="text-[var(--color-muted)] leading-relaxed mb-5">
          A self-hosted PaaS for your Docker Swarm — connect a repo, it builds an image
          and runs it behind HTTPS. If this was useful, a star helps other people find it.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <a href="https://github.com/hikmahtech/koyracloud" target="_blank" rel="noreferrer"
             className="btn btn-primary no-underline">★ Star on GitHub</a>
          <a href="/docs" className="btn btn-ghost no-underline">Read the docs</a>
        </div>
      </div>
      <p className="mono text-xs text-[var(--color-muted)] mt-5">
        Built and maintained by{" "}
        <a href="https://hikmahtechnologies.com" target="_blank" rel="noreferrer"
           className="text-acid no-underline hover:underline">Hikmah Technologies</a>
        {" "}· running in production for real client apps.
      </p>
    </div>
  );
}

// Small wrapper so the SEO hook runs with the resolved post (keeps the early
// return above hook-free and the rules-of-hooks happy).
function SeoHead({ post, url, jsonLd }) {
  useSeo({ title: `${post.title} — koyracloud`, description: post.description, canonical: url, jsonLd });
  return null;
}
