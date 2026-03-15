export default function Footer() {
  return (
    <footer className="flex items-center justify-between px-6 py-3 border-t border-[var(--border)] shrink-0">
      <div className="flex gap-4">
        <a
          href="https://x.com/ensue_ai"
          className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition-colors"
          target="_blank"
          rel="noopener"
        >
          X
        </a>
        <a
          href="https://discord.gg/JpJAmEwEEs"
          className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition-colors"
          target="_blank"
          rel="noopener"
        >
          Discord
        </a>
        <a
          href="https://github.com/mutable-state-inc/autoresearch-at-home"
          className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition-colors"
          target="_blank"
          rel="noopener"
        >
          GitHub
        </a>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex gap-3">
          <button className="text-xs uppercase tracking-[0.1em] text-[var(--accent)] border-b border-[var(--accent)] cursor-pointer">
            Timeline
          </button>
          <button className="text-xs uppercase tracking-[0.1em] text-[var(--muted)] hover:text-[var(--foreground)] cursor-pointer transition-colors">
            Strategies
          </button>
        </div>
      </div>
      <div className="text-xs text-[var(--muted)]">
        Powered by{" "}
        <a
          href="https://ensue.dev"
          className="text-[var(--accent)] hover:underline"
          target="_blank"
          rel="noopener"
        >
          Ensue
        </a>
        {" + "}
        <span className="text-[var(--foreground)]">Bittensor</span>
      </div>
    </footer>
  );
}
