"use client";

import { useState } from "react";

export default function JoinCard() {
  const [copied, setCopied] = useState(false);

  const message =
    "git clone https://github.com/mutable-state-inc/autoresearch-tao && cd autoresearch-tao && pip install -r requirements.txt && python miner.py --miner-id <your-name> --validator <validator-url>";

  const handleCopy = () => {
    navigator.clipboard.writeText(message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="border border-[var(--accent-dim)] rounded-lg bg-[var(--card)] p-4">
      <h3 className="text-xs uppercase tracking-[0.15em] text-[var(--accent)] font-medium mb-1">
        Start mining
      </h3>
      <p className="text-xs text-[var(--muted)] mb-3">
        Clone, install, and run — your miner auto-registers with the validator
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
      <div className="mt-3 text-xs space-y-1">
        <div>
          <span className="text-[var(--muted)]">Remote? Use </span>
          <span className="text-[var(--muted-light)] font-mono">--external-url</span>
          <span className="text-[var(--muted)]"> with your ngrok/public URL</span>
        </div>
        <div>
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
    </div>
  );
}
