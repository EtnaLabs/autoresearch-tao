"use client";

import type { FeedItem } from "@/lib/use-live-data";

function timeAgo(ts: number): string {
  const mins = Math.floor((Date.now() - ts) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}

interface Props {
  items: FeedItem[];
}

export default function LiveFeed({ items }: Props) {
  return (
    <div className="border border-[var(--card-border)] rounded-lg bg-[var(--card)] p-4">
      <h3 className="text-xs uppercase tracking-[0.15em] text-[var(--muted)] mb-3 font-medium">
        Live Research Feed
      </h3>
      <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
        {items.map((item, i) => (
          <div key={`${item.agentId}-${item.timestamp}-${i}`} className="text-sm">
            <div className="truncate">
              <span className="font-mono text-xs text-[var(--muted-light)]">
                Result: [{item.agentId}{" "}
                <span
                  className={
                    item.status === "completed"
                      ? "text-[var(--keep)]"
                      : "text-[var(--muted)]"
                  }
                >
                  {item.status.toUpperCase()}
                </span>
                ] val_bpb={item.valBpb.toFixed(6)} (delta=
                <span className={item.delta < 0 ? "text-[var(--keep)]" : "text-[var(--muted)]"}>
                  {item.delta >= 0 ? "+" : ""}
                  {item.delta.toFixed(4)}
                </span>
                ) | {item.description}
              </span>
            </div>
            <div className="text-xs text-[var(--muted)]">
              {timeAgo(item.timestamp)} by {item.agentId}
            </div>
          </div>
        ))}
        {items.length === 0 && (
          <div className="text-sm text-[var(--muted)] text-center py-4">
            No experiments yet
          </div>
        )}
      </div>
    </div>
  );
}
