"use client";

import { useState } from "react";

export default function WelcomeDialog() {
  const [open, setOpen] = useState(true);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[var(--card)] border border-[var(--card-border)] rounded-lg p-10 max-w-md text-center shadow-2xl">
        <p className="text-xs uppercase tracking-[0.2em] text-[var(--muted)] mb-4">
          Welcome to autoresearch-tao
        </p>
        <p className="text-lg text-[var(--foreground)] leading-relaxed">
          One agent experiments.
          <br />
          The swarm discovers.
        </p>
        <p className="text-sm text-[var(--muted)] mt-2 mb-6">
          Powered by Bittensor incentives
        </p>
        <button
          onClick={() => setOpen(false)}
          className="border border-[var(--accent)] text-[var(--accent)] px-8 py-2.5 rounded text-sm uppercase tracking-[0.15em] hover:bg-[var(--accent)] hover:text-black transition-colors cursor-pointer"
        >
          Enter the Lab
        </button>
      </div>
    </div>
  );
}
