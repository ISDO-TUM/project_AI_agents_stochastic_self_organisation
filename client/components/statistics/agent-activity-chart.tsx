"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getTheme } from "@/lib/theme";
import type { AgentStat } from "@/lib/types";

export function AgentActivityChart({
  agents,
  dark,
}: {
  agents: AgentStat[];
  dark: boolean;
}) {
  const t = getTheme(dark);
  const chartHeight = Math.max(280, agents.length * 42 + 48);
  const yAxisWidth = Math.min(
    220,
    Math.max(96, ...agents.map((a) => a.agentName.length * 7)),
  );
  const data = agents.map((a) => ({
    name: a.agentName,
    Sent: a.messagesSent,
    Received: a.messagesReceived,
    Tools: a.toolInvocations,
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
        Per-agent activity
      </div>
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 8, right: 20, bottom: 8, left: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={t.border} />
          <XAxis
            type="number"
            stroke={t.textSub}
            fontSize={11}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            stroke={t.textSub}
            fontSize={11}
            width={yAxisWidth}
            interval={0}
          />
          <Tooltip
            contentStyle={{
              background: t.surface,
              border: `1px solid ${t.border}`,
              color: t.text,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: t.textSub }} />
          <Bar dataKey="Sent" fill="#8b1a2f" />
          <Bar dataKey="Received" fill="#5a8bce" />
          <Bar dataKey="Tools" fill="#d8b15a" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
