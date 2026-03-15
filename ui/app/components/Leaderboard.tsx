"use client";

import { useState } from "react";
import { getAgentColor, type Agent } from "@/lib/use-live-data";

type Tab = "best" | "tao" | "experiments" | "improvers";

interface Props {
  agents: Agent[];
}

export default function Leaderboard({ agents }: Props) {
  const [tab, setTab] = useState<Tab>("best");

  const sorted = [...agents].sort((a, b) => {
    if (tab === "best") return a.bestBpb - b.bestBpb;
    if (tab === "tao") return b.taoEarned - a.taoEarned;
    if (tab === "experiments") return b.experiments - a.experiments;
    if (tab === "improvers") return b.improvements - a.improvements;
    return 0;
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "best", label: "Best BPB" },
    { key: "tao", label: "TAO Earned" },
    { key: "experiments", label: "Most Runs" },
    { key: "improvers", label: "Improvers" },
  ];

  function renderMetric(agent: Agent) {
    switch (tab) {
      case "best":
        return (
          <span className="text-sm font-mono text-[var(--muted-light)]">
            {agent.bestBpb.toFixed(6)}
          </span>
        );
      case "tao":
        return (
          <span className="text-sm font-mono text-[var(--accent)]">
            {agent.taoEarned.toFixed(4)} TAO
          </span>
        );
      case "experiments":
        return (
          <span className="text-sm font-mono text-[var(--muted-light)]">
            {agent.experiments} runs
          </span>
        );
      case "improvers":
        return (
          <span className="text-sm font-mono text-[var(--keep)]">
            {agent.improvements} improvements
          </span>
        );
    }
  }

  return (
    <div className="border border-[var(--card-border)] rounded-lg bg-[var(--card)] p-4">
      <h3 className="text-xs uppercase tracking-[0.15em] text-[var(--muted)] mb-4 font-medium">
        autoresearch-tao leaderboard
      </h3>
      <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
        {sorted.map((agent, i) => (
          <div key={agent.id} className="flex items-center gap-3">
            <span className="text-xs text-[var(--muted)] w-6 text-right font-mono">
              #{i + 1}
            </span>
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0"
              style={{ backgroundColor: getAgentColor(agent.id) }}
            >
              {agent.name[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{agent.name}</div>
              {tab !== "tao" && agent.taoEarned > 0 && (
                <div className="text-xs font-mono text-[var(--accent)] opacity-70">
                  {agent.taoEarned.toFixed(4)} TAO
                </div>
              )}
            </div>
            <div className="text-right shrink-0">
              {renderMetric(agent)}
            </div>
          </div>
        ))}
        {sorted.length === 0 && (
          <div className="text-sm text-[var(--muted)] text-center py-4">
            No agents yet
          </div>
        )}
      </div>
      <div className="flex gap-3 mt-4 pt-3 border-t border-[var(--border)]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`text-xs uppercase tracking-[0.1em] cursor-pointer transition-colors ${
              tab === t.key
                ? "text-[var(--accent)] border-b border-[var(--accent)]"
                : "text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
