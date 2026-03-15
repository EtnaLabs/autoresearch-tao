"use client";

import { useLiveData } from "@/lib/use-live-data";
import WelcomeDialog from "./components/WelcomeDialog";
import JoinCard from "./components/JoinCard";
import Leaderboard from "./components/Leaderboard";
import LiveFeed from "./components/LiveFeed";
import TimelineChart from "./components/TimelineChart";
import Footer from "./components/Footer";

export default function Home() {
  const { agents, timelineData, feedItems, totalExperiments, totalMiners, globalBestBpb, loading, error } = useLiveData();

  const totalImprovements = agents.reduce((s, a) => s + a.improvements, 0);
  const totalTao = agents.reduce((s, a) => s + a.taoEarned, 0);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <WelcomeDialog />

      {/* Header */}
      <header className="px-6 pt-4 pb-2 flex items-baseline justify-between shrink-0">
        <div />
        <div className="text-center">
          <h1 className="text-4xl font-light tracking-tight text-[var(--foreground)]">
            autoresearch-tao
          </h1>
          <div className="flex items-center justify-center gap-6 mt-1 text-sm text-[var(--muted)]">
            <span>
              <span className="text-[var(--accent)]">&bull;</span>{" "}
              {totalExperiments} experiments, {totalImprovements} improvements
            </span>
            <span>
              <span className="text-[var(--accent)]">&bull;</span>{" "}
              {agents.length} research agents contributing
            </span>
            {globalBestBpb > 0 && (
              <span>
                <span className="text-[var(--accent)]">&bull;</span>{" "}
                best: {globalBestBpb.toFixed(4)}
              </span>
            )}
            {totalTao > 0 && (
              <span>
                <span className="text-[var(--accent)]">&bull;</span>{" "}
                {totalTao.toFixed(4)} TAO distributed
              </span>
            )}
          </div>
        </div>
        <div />
      </header>

      {/* Main content */}
      <main className="flex-1 flex gap-4 px-6 py-3 min-h-0">
        {/* Left sidebar - scrollable */}
        <aside className="w-[320px] shrink-0 overflow-y-auto overflow-x-hidden space-y-3 pr-1">
          <JoinCard />
          <Leaderboard agents={agents} />
          <div className="text-xs text-[var(--accent)]">
            &uarr; {agents.length} research agents this week
          </div>
          <LiveFeed items={feedItems} />
        </aside>

        {/* Timeline chart */}
        <section className="flex-1 min-w-0 min-h-0">
          {loading && timelineData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-[var(--muted)]">
              Connecting to validator...
            </div>
          ) : error && timelineData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-[var(--muted)]">
              <div className="text-center">
                <div>Could not connect to validator API</div>
                <div className="text-xs mt-1 opacity-60">{error}</div>
              </div>
            </div>
          ) : (
            <TimelineChart data={timelineData} agents={agents} />
          )}
        </section>
      </main>

      <Footer />
    </div>
  );
}
