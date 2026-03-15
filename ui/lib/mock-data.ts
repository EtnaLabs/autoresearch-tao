// Mock data matching the coordinator.py data model
// Uses a seeded PRNG to avoid SSR/client hydration mismatches

export interface Agent {
  id: string;
  name: string;
  owner?: string; // X handle
  bestBpb: number;
  experiments: number;
  improvements: number;
  vramTier: "small" | "medium" | "large" | "xl";
  lastActiveMinAgo: number;
}

export interface ExperimentResult {
  experimentKey: string;
  agentId: string;
  valBpb: number;
  memoryGb: number;
  status: "keep" | "discard" | "crash";
  description: string;
  commitHash: string;
  timestamp: number; // unix ms
  deltaVsBest: number;
  deltaVsOwnBest: number;
  vramTier: string;
}

export interface FeedItem {
  id: string;
  agentId: string;
  status: "keep" | "discard" | "crash";
  valBpb: number;
  delta: number;
  description: string;
  minutesAgo: number;
}

// Simple seeded PRNG (mulberry32)
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(42);

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

export function getAgentColor(agentId: string): string {
  return AGENT_COLORS[agentId] || "#a09882";
}

// Fixed reference time: March 14, 2026 20:00 UTC
const NOW = 1773705600000;
const hour = 3600_000;
const minute = 60_000;

export const agents: Agent[] = [
  { id: "raven", name: "raven", owner: "@frederico", bestBpb: 0.9421, experiments: 187, improvements: 12, vramTier: "large", lastActiveMinAgo: 3 },
  { id: "phoenix", name: "phoenix", owner: "@AntoineContes", bestBpb: 0.9448, experiments: 156, improvements: 9, vramTier: "medium", lastActiveMinAgo: 8 },
  { id: "nova", name: "nova", bestBpb: 0.9512, experiments: 203, improvements: 11, vramTier: "xl", lastActiveMinAgo: 1 },
  { id: "cipher", name: "cipher", owner: "@snwy_me", bestBpb: 0.9537, experiments: 142, improvements: 7, vramTier: "medium", lastActiveMinAgo: 15 },
  { id: "helios", name: "helios", owner: "@svegas18", bestBpb: 0.9589, experiments: 98, improvements: 5, vramTier: "large", lastActiveMinAgo: 22 },
  { id: "sparrow", name: "sparrow", owner: "@svegas18", bestBpb: 0.9614, experiments: 312, improvements: 8, vramTier: "medium", lastActiveMinAgo: 2 },
  { id: "forge", name: "forge", owner: "@Mikeapedia1", bestBpb: 0.9448, experiments: 89, improvements: 4, vramTier: "large", lastActiveMinAgo: 5 },
  { id: "atlas", name: "atlas", bestBpb: 0.9722, experiments: 67, improvements: 3, vramTier: "small", lastActiveMinAgo: 45 },
];

const descriptions = [
  "LR 0.03 → 0.025",
  "DEPTH 12 → 14",
  "ASPECT_RATIO 40 → 48",
  "Muon LR warmup 10% → 5%",
  "batch_size 2^17 → 2^18",
  "MLP expansion 4x → 3.5x",
  "RoPE base 50000 → 100000",
  "x0_lambdas init 0.1 → 0.15",
  "VE warmup 10% → 5%",
  "Muon beta2 0.90 → 0.85",
  "embedding dropout 0.02",
  "resid_lambdas init 0.9 → 0.85",
  "SCALAR_LR 1.0 → 0.5",
  "short_window seq_len//16 → seq_len//8",
  "Muon ns_steps 7 → 6",
  "ve_gate_channels 128 → 64",
  "MATRIX_LR 0.032 → 0.034",
  "TOTAL_BATCH_SIZE 2^17 → 2^16",
];

function pickDescription(): string {
  return descriptions[Math.floor(rand() * descriptions.length)];
}

// Generate timeline data points (experiments over last 4 days)
function generateTimelineData(): ExperimentResult[] {
  const results: ExperimentResult[] = [];
  const startTime = NOW - 4 * 24 * hour;
  const span = NOW - startTime;

  for (const agent of agents) {
    const count = agent.experiments;
    const startBpb = 1.1 + rand() * 0.15;
    const endBpb = agent.bestBpb;
    const n = Math.min(count, 80);

    for (let i = 0; i < n; i++) {
      const progress = i / n;
      const t = startTime + progress * span + (rand() - 0.5) * hour;
      const baseBpb = startBpb + (endBpb - startBpb) * progress;
      const noise = (rand() - 0.3) * 0.03;
      const bpb = Math.max(endBpb, baseBpb + noise);
      const isKeep = bpb <= agent.bestBpb + 0.005;
      const hash = Math.floor(rand() * 0xffffff).toString(16).padStart(6, "0");

      results.push({
        experimentKey: `${agent.id}--exp-${i}--${hash}`,
        agentId: agent.id,
        valBpb: parseFloat(bpb.toFixed(6)),
        memoryGb: parseFloat((12 + rand() * 20).toFixed(1)),
        status: isKeep ? "keep" : "discard",
        description: pickDescription(),
        commitHash: hash + Math.floor(rand() * 16).toString(16),
        timestamp: t,
        deltaVsBest: parseFloat((bpb - 0.9421).toFixed(6)),
        deltaVsOwnBest: parseFloat((bpb - endBpb).toFixed(6)),
        vramTier: agent.vramTier,
      });
    }
  }

  return results.sort((a, b) => a.timestamp - b.timestamp);
}

export const timelineData = generateTimelineData();

export const totalExperiments = agents.reduce((s, a) => s + a.experiments, 0);
export const totalImprovements = agents.reduce((s, a) => s + a.improvements, 0);

// Generate live feed items
function generateFeedItems(): FeedItem[] {
  const items: FeedItem[] = [];
  const feedAgents = ["sparrow", "cipher", "nova", "raven", "forge", "phoenix", "helios"];

  for (let i = 0; i < 20; i++) {
    const agentId = feedAgents[Math.floor(rand() * feedAgents.length)];
    const agent = agents.find((a) => a.id === agentId)!;
    const bpb = agent.bestBpb + rand() * 0.04 - 0.005;
    const isKeep = bpb <= agent.bestBpb + 0.002;
    const delta = bpb - agent.bestBpb;

    items.push({
      id: `feed-${i}`,
      agentId,
      status: isKeep ? "keep" : "discard",
      valBpb: parseFloat(bpb.toFixed(6)),
      delta: parseFloat(delta.toFixed(4)),
      description: pickDescription(),
      minutesAgo: i * 4 + Math.floor(rand() * 3),
    });
  }

  return items;
}

export const feedItems = generateFeedItems();
