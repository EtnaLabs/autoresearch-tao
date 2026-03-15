"use client";

import { useState, useMemo } from "react";
import Image from "next/image";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from "recharts";
import { getAgentColor, type Agent, type TimelinePoint } from "@/lib/use-live-data";

function formatDate(ts: number): string {
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
}

interface Props {
  data: TimelinePoint[];
  agents: Agent[];
}

/** Build the step-line path for running best BPB (horizontal, then vertical on improvement). */
function buildRunningBestSteps(data: TimelinePoint[]): { timestamp: number; valBpb: number }[] {
  if (data.length === 0) return [];

  // Sort all completed experiments by timestamp
  const sorted = [...data]
    .filter((d) => d.status === "completed")
    .sort((a, b) => a.timestamp - b.timestamp);

  if (sorted.length === 0) return [];

  const steps: { timestamp: number; valBpb: number }[] = [];
  let bestBpb = Infinity;

  for (const point of sorted) {
    if (point.valBpb < bestBpb) {
      // Add horizontal segment: extend previous best to this timestamp
      if (steps.length > 0) {
        steps.push({ timestamp: point.timestamp, valBpb: bestBpb });
      }
      // Vertical drop to new best
      bestBpb = point.valBpb;
      steps.push({ timestamp: point.timestamp, valBpb: bestBpb });
    }
  }

  // Extend horizontal line to the last experiment's timestamp
  if (sorted.length > 0 && steps.length > 0) {
    const lastTs = sorted[sorted.length - 1].timestamp;
    if (steps[steps.length - 1].timestamp < lastTs) {
      steps.push({ timestamp: lastTs, valBpb: bestBpb });
    }
  }

  return steps;
}

/** Identify which points are new global bests. */
function markImprovements(data: TimelinePoint[]): Set<number> {
  const sorted = [...data]
    .filter((d) => d.status === "completed")
    .sort((a, b) => a.timestamp - b.timestamp);

  const bestIndices = new Set<number>();
  let bestBpb = Infinity;

  for (const point of sorted) {
    if (point.valBpb < bestBpb) {
      bestBpb = point.valBpb;
      // Find original index in data
      const origIdx = data.indexOf(point);
      if (origIdx !== -1) bestIndices.add(origIdx);
    }
  }

  return bestIndices;
}

type ScaleMode = "linear" | "log" | "focus";

export default function TimelineChart({ data, agents }: Props) {
  const [selectedAgent, setSelectedAgent] = useState<string>("all");
  const [scaleMode, setScaleMode] = useState<ScaleMode>("focus");

  const filteredData = useMemo(() => {
    if (selectedAgent === "all") return data;
    return data.filter((d) => d.agentId === selectedAgent);
  }, [selectedAgent, data]);

  const completedData = useMemo(
    () => filteredData.filter((d) => d.status === "completed"),
    [filteredData],
  );

  const improvementIndices = useMemo(() => markImprovements(filteredData), [filteredData]);

  // Split into "regular" (gray) and "improvement" (green) points
  const regularPoints = useMemo(
    () => filteredData.filter((_, i) => !improvementIndices.has(i) && filteredData[i]?.status === "completed"),
    [filteredData, improvementIndices],
  );

  const improvementPoints = useMemo(
    () => filteredData.filter((_, i) => improvementIndices.has(i)),
    [filteredData, improvementIndices],
  );

  // Step-line data for running best
  const stepLineData = useMemo(() => buildRunningBestSteps(filteredData), [filteredData]);

  // Focus mode: compute Y domain that zooms into the improvement region
  const yDomain = useMemo(() => {
    if (scaleMode !== "focus" || completedData.length === 0) return undefined;
    const bpbs = completedData.map((d) => d.valBpb).sort((a, b) => a - b);
    const bestBpb = bpbs[0];
    const baseline = bpbs[Math.floor(bpbs.length * 0.75)];
    const range = baseline - bestBpb;
    return [bestBpb - range * 0.15, baseline + range * 0.15] as [number, number];
  }, [scaleMode, completedData]);

  return (
    <div className="relative h-full flex flex-col">
      {/* Bittensor logo watermark */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-0">
        <Image
          src="/bittensor-logo.svg"
          alt=""
          width={240}
          height={257}
          className="opacity-[0.04]"
          style={{ filter: "invert(1)" }}
          priority
        />
      </div>

      {/* Controls */}
      <div className="absolute top-0 right-0 z-10 flex items-center gap-2">
        <div className="flex rounded overflow-hidden border border-[#222]">
          {(["linear", "log", "focus"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setScaleMode(mode)}
              className={`text-xs px-2 py-1 transition-colors capitalize ${
                scaleMode === mode
                  ? "bg-[#00d4aa] text-black"
                  : "bg-[#141414] text-[#6b6b6b] hover:text-[#e8e8e8]"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
        <select
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          className="text-xs bg-[#141414] border border-[#222] rounded px-2 py-1 text-[#e8e8e8] cursor-pointer focus:border-[#00d4aa] focus:outline-none"
        >
          <option value="all">All agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      <ResponsiveContainer width="100%" className="flex-1 min-h-0 relative z-[1]">
        <ComposedChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatDate}
            tick={{ fontSize: 11, fill: "#6b6b6b" }}
            stroke="#1e1e1e"
            name="Time"
            allowDuplicatedCategory={false}
          />
          <YAxis
            dataKey="valBpb"
            type="number"
            scale={scaleMode === "log" ? "log" : "linear"}
            domain={yDomain || ["auto", "auto"]}
            tickFormatter={(v: number) => v.toFixed(2)}
            tick={{ fontSize: 11, fill: "#6b6b6b" }}
            stroke="#1e1e1e"
            name="Validation BPB"
            label={{
              value: `Validation BPB — ${scaleMode} scale (lower is better)`,
              angle: -90,
              position: "insideLeft",
              style: { fontSize: 11, fill: "#6b6b6b" },
              offset: -5,
            }}
          />
          <Tooltip
            content={({ payload }) => {
              if (!payload || payload.length === 0) return null;
              const d = payload[0].payload;
              if (!d?.agentId) return null;
              const isImprovement = improvementPoints.some(
                (p) => p.timestamp === d.timestamp && p.valBpb === d.valBpb,
              );
              return (
                <div className="bg-[#1a1a1a] border border-[#333] rounded p-2.5 text-xs shadow-xl">
                  <div className="font-medium text-[#e8e8e8]">{d.agentId}</div>
                  <div className={`font-mono ${isImprovement ? "text-[#2ecc71]" : "text-[#8a8a8a]"}`}>
                    val_bpb: {d.valBpb?.toFixed(6)}
                  </div>
                  {isImprovement && (
                    <div className="text-[#2ecc71] font-medium">NEW BEST</div>
                  )}
                  <div className="text-[#8a8a8a]">{d.description}</div>
                  <div className="text-[#6b6b6b]">
                    {new Date(d.timestamp).toLocaleString()}
                  </div>
                </div>
              );
            }}
          />

          {/* Step line for running best */}
          <Line
            data={stepLineData}
            dataKey="valBpb"
            stroke="#27ae60"
            strokeWidth={2}
            strokeOpacity={0.7}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />

          {/* Regular experiments: faint gray dots */}
          <Scatter
            name="experiments"
            data={regularPoints}
            fill="#666666"
            opacity={0.35}
            r={3}
          />

          {/* Improvement points: green, larger */}
          <Scatter
            name="improvements"
            data={improvementPoints}
            fill="#2ecc71"
            opacity={1}
            r={5}
            stroke="#000"
            strokeWidth={0.5}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 justify-end mt-1 px-4">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "#666666", opacity: 0.35 }} />
          <span className="text-xs text-[#6b6b6b]">experiments</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "#2ecc71" }} />
          <span className="text-xs text-[#6b6b6b]">new best</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-4 h-0.5" style={{ backgroundColor: "#27ae60", opacity: 0.7 }} />
          <span className="text-xs text-[#6b6b6b]">running best</span>
        </div>
      </div>
    </div>
  );
}
