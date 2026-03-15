"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_VALIDATOR_URL || "http://localhost:8092";
const POLL_INTERVAL = 5_000; // 5 seconds

export interface Agent {
  id: string;
  name: string;
  bestBpb: number;
  experiments: number;
  improvements: number;
  score: number;
  lastSeen: number;
  taoEarned: number;
}

export interface TimelinePoint {
  experimentKey: string;
  agentId: string;
  valBpb: number;
  memoryGb: number;
  status: string;
  description: string;
  timestamp: number;
}

export interface FeedItem {
  agentId: string;
  status: string;
  valBpb: number;
  delta: number;
  description: string;
  timestamp: number;
  score: number;
}

interface LiveData {
  agents: Agent[];
  timelineData: TimelinePoint[];
  feedItems: FeedItem[];
  totalExperiments: number;
  totalMiners: number;
  globalBestBpb: number;
  loading: boolean;
  error: string | null;
}

const AGENT_COLORS: Record<string, string> = {
  raven: "#00d4aa",
  phoenix: "#38bdf8",
  nova: "#a78bfa",
  cipher: "#f472b6",
  helios: "#fb923c",
  sparrow: "#4ade80",
  forge: "#facc15",
  atlas: "#22d3ee",
};

const PALETTE = ["#00d4aa", "#38bdf8", "#a78bfa", "#f472b6", "#fb923c", "#4ade80", "#facc15", "#22d3ee"];

export function getAgentColor(agentId: string): string {
  if (AGENT_COLORS[agentId]) return AGENT_COLORS[agentId];
  // Deterministic color for unknown agents
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) hash = (hash * 31 + agentId.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

export function useLiveData(): LiveData {
  const [data, setData] = useState<LiveData>({
    agents: [],
    timelineData: [],
    feedItems: [],
    totalExperiments: 0,
    totalMiners: 0,
    globalBestBpb: 0,
    loading: true,
    error: null,
  });

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/all`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();

      const agents: Agent[] = (json.leaderboard || []).map((e: Record<string, unknown>) => ({
        id: e.id,
        name: e.name,
        bestBpb: e.bestBpb,
        experiments: e.experiments,
        improvements: e.improvements,
        score: e.score,
        lastSeen: e.lastSeen,
        taoEarned: (e.taoEarned as number) || 0,
      }));

      const timelineData: TimelinePoint[] = (json.results || []).map((r: Record<string, unknown>) => ({
        experimentKey: r.experiment_key,
        agentId: r.agent_id,
        valBpb: r.val_bpb,
        memoryGb: r.memory_gb,
        status: r.status,
        description: r.description,
        timestamp: (r.timestamp as number) * 1000, // seconds to ms
      }));

      const feedItems: FeedItem[] = (json.feed || []).map((f: Record<string, unknown>) => ({
        agentId: f.agentId,
        status: f.status,
        valBpb: f.valBpb,
        delta: f.delta,
        description: f.description,
        timestamp: (f.timestamp as number) * 1000,
        score: f.score,
      }));

      setData({
        agents,
        timelineData,
        feedItems,
        totalExperiments: json.totalExperiments || 0,
        totalMiners: json.totalMiners || 0,
        globalBestBpb: json.globalBestBpb || 0,
        loading: false,
        error: null,
      });
    } catch (err) {
      setData((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : "Failed to fetch",
      }));
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchData]);

  return data;
}
