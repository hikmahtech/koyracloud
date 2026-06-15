import { Link } from "react-router-dom";

export function Logo({ size = 22 }) {
  return (
    <span className="inline-flex items-center gap-2.5 font-display font-semibold tracking-tight"
          style={{ fontSize: size }}>
      <svg width={size - 2} height={size - 2} viewBox="0 0 24 24" fill="none" aria-hidden>
        <rect x="2" y="2" width="20" height="20" rx="5" stroke="var(--color-acid)" strokeWidth="2" />
        <circle cx="12" cy="12" r="3.5" fill="var(--color-acid)" />
      </svg>
      koyracloud
    </span>
  );
}

export function PublicNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-[var(--color-line)]
                       bg-[rgba(10,11,13,0.72)] backdrop-blur">
      <nav className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link to="/" className="text-[var(--color-fg)] no-underline"><Logo /></Link>
        <div className="flex items-center gap-7 text-sm">
          <Link to="/docs" className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">Docs</Link>
          <Link to="/blog" className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">Blog</Link>
          <a href="/api/auth/login" className="btn btn-primary">Sign in</a>
        </div>
      </nav>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-[var(--color-line)] mt-32">
      <div className="max-w-6xl mx-auto px-6 py-12 flex flex-wrap gap-8 items-center justify-between">
        <Logo size={18} />
        <div className="flex gap-7 text-sm text-[var(--color-muted)]">
          <Link to="/docs" className="hover:text-[var(--color-fg)] no-underline text-inherit">Docs</Link>
          <Link to="/blog" className="hover:text-[var(--color-fg)] no-underline text-inherit">Blog</Link>
          <a href="https://github.com/hikmahtech/koyracloud" target="_blank" rel="noreferrer"
             className="hover:text-[var(--color-fg)] no-underline text-inherit">GitHub</a>
          <a href="/api/auth/login" className="hover:text-[var(--color-fg)] no-underline text-inherit">Sign in</a>
        </div>
        <span className="mono text-xs text-[var(--color-muted)]">self-hosted · single-operator · {new Date().getFullYear()}</span>
      </div>
    </footer>
  );
}
