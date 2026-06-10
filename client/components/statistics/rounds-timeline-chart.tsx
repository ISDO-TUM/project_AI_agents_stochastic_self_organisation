"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getTheme } from "@/lib/theme";
import type { RoundStat } from "@/lib/types";

export function RoundsTimelineChart({
  rounds,
  dark,
}: {
  rounds: RoundStat[];
  dark: boolean;
}) {
  const t = getTheme(dark);
  const data = rounds.map((r) => ({
    round: `R${r.roundIndex}`,
    Messages: r.messageCount,
    "Active edges": r.activeEdgeCount,
  }));

  return (
    <div
      style={{
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        padding: 16,
        minHeight: 330,
      }}
    >
      <div
        style={{
          color: t.text,
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        Self-organisation over rounds
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke={t.border} />
          <XAxis dataKey="round" stroke={t.textSub} fontSize={11} />
          <YAxis stroke={t.textSub} fontSize={11} allowDecimals={false} />
          <Tooltip
            contentStyle={{
              background: t.surface,
              border: `1px solid ${t.border}`,
              color: t.text,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: t.textSub }} />
          <Line
            type="monotone"
            dataKey="Messages"
            stroke="#8b1a2f"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="Active edges"
            stroke="#6ec1a8"
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
