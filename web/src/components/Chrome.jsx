import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

// ponytail: one localStorage-backed theme hook; no provider/context for a single boolean.
export function useTheme() {
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme || "dark"
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";
  return (
    <button onClick={toggle} className="theme-toggle"
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label="Toggle color theme">
      {dark ? (
        /* moon */
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        /* sun */
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      )}
    </button>
  );
}

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
                       bg-[var(--color-nav)] backdrop-blur">
      <nav className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link to="/" className="text-[var(--color-fg)] no-underline"><Logo /></Link>
        <div className="flex items-center gap-7 text-sm">
          <Link to="/docs" className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">Docs</Link>
          <Link to="/blog" className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">Blog</Link>
          <a href="https://github.com/hikmahtech/koyracloud" target="_blank" rel="noreferrer"
             className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">GitHub ↗</a>
          <ThemeToggle />
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
        <span className="mono text-xs text-[var(--color-muted)]">
          self-hosted · single-operator ·{" "}
          <a href="https://hikmahtechnologies.com" target="_blank" rel="noreferrer"
             className="hover:text-[var(--color-fg)] no-underline text-inherit">Hikmah Technologies</a>
          {" "}· {new Date().getFullYear()}
        </span>
      </div>
    </footer>
  );
}
