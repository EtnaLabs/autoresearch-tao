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

export default function TimelineChart({ data, agents }: Props) {
  const [selectedAgent, setSelectedAgent] = useState<string>("all");

  const filteredData = useMemo(() => {
    if (selectedAgent === "all") return data;
    return data.filter((d) => d.agentId === selectedAgent);
  }, [selectedAgent, data]);

  const agentGroups = useMemo(() => {
    const groups: Record<string, TimelinePoint[]> = {};
    for (const d of filteredData) {
      if (!groups[d.agentId]) groups[d.agentId] = [];
      groups[d.agentId].push(d);
    }
    return groups;
  }, [filteredData]);

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

      {/* Agent filter dropdown */}
      <div className="absolute top-0 right-0 z-10">
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
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatDate}
            tick={{ fontSize: 11, fill: "#6b6b6b" }}
            stroke="#1e1e1e"
            name="Time"
          />
          <YAxis
            dataKey="valBpb"
            type="number"
            domain={["auto", "auto"]}
            tick={{ fontSize: 11, fill: "#6b6b6b" }}
            stroke="#1e1e1e"
            name="Validation BPB"
            label={{
              value: "Validation BPB (lower is better)",
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
              return (
                <div className="bg-[#1a1a1a] border border-[#333] rounded p-2.5 text-xs shadow-xl">
                  <div className="font-medium text-[#e8e8e8]">{d.agentId}</div>
                  <div className="font-mono text-[#00d4aa]">
                    val_bpb: {d.valBpb?.toFixed(6)}
                  </div>
                  <div className="text-[#8a8a8a]">{d.description}</div>
                  <div
                    className={
                      d.status === "completed" ? "text-[#00d4aa]" : "text-[#6b6b6b]"
                    }
                  >
                    {d.status?.toUpperCase()}
                  </div>
                  <div className="text-[#6b6b6b]">
                    {new Date(d.timestamp).toLocaleString()}
                  </div>
                </div>
              );
            }}
          />
          {Object.entries(agentGroups).map(([agentId, groupData]) => (
            <Scatter
              key={agentId}
              name={agentId}
              data={groupData}
              fill={getAgentColor(agentId)}
              opacity={0.75}
              r={3}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 justify-end mt-1 px-4">
        {Object.keys(agentGroups).map((agentId) => (
          <div key={agentId} className="flex items-center gap-1.5">
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: getAgentColor(agentId) }}
            />
            <span className="text-xs text-[#6b6b6b]">{agentId}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
