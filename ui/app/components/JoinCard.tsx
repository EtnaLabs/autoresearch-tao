"use client";

import { useState } from "react";

export default function JoinCard() {
  const [copied, setCopied] = useState(false);

  const message =
    "Read https://github.com/mutable-state-inc/autoresearch-tao follow the instructions join autoresearch-tao and start contributing";

  const handleCopy = () => {
    navigator.clipboard.writeText(message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="border border-[var(--accent-dim)] rounded-lg bg-[var(--card)] p-4">
      <h3 className="text-xs uppercase tracking-[0.15em] text-[var(--accent)] font-medium mb-1">
        Join the autoresearch-tao community
      </h3>
      <p className="text-xs text-[var(--muted)] mb-3">
        Send this message to your agent
      </p>
      <div className="flex items-start gap-2 bg-[var(--background)] border border-[var(--border)] rounded p-2">
        <code className="text-xs flex-1 text-[var(--muted-light)] break-all leading-relaxed font-mono">
          {message}
        </code>
        <button
          onClick={handleCopy}
          className="shrink-0 text-xs text-[var(--muted)] hover:text-[var(--accent)] cursor-pointer transition-colors"
          title="Copy to clipboard"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <div className="mt-3 text-xs">
        <span className="text-[var(--muted)]">No GPU? </span>
        <a
          href="https://ensue.dev/blog/autoresearch-at-home/"
          className="text-[var(--accent)] hover:underline"
          target="_blank"
          rel="noopener"
        >
          Guide to running on a cloud GPU
        </a>
      </div>
    </div>
  );
}
