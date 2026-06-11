"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartLegend,
  StatCard,
  chartTooltipProps,
} from "@/components/statistics/primitives";
import { getTheme } from "@/lib/theme";
import type { RoundStat } from "@/lib/types";

const MSG_COLOR = "#c4374f";
const EDGE_COLOR = "#6ec1a8";

export function RoundsTimelineChart({
  rounds,
  dark,
  delay = 0,
}: {
  rounds: RoundStat[];
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  const tt = chartTooltipProps(dark);
  const data = rounds.map((r) => ({
    round: `R${r.roundIndex}`,
    Messages: r.messageCount,
    "Active edges": r.activeEdgeCount,
  }));

  return (
    <StatCard
      title="Self-organisation over rounds"
      icon="Activity"
      dark={dark}
      delay={delay}
      minHeight={320}
      meta={
        <ChartLegend
          items={[
            { label: "Messages", color: MSG_COLOR },
            { label: "Active edges", color: EDGE_COLOR },
          ]}
          dark={dark}
        />
      }
    >
      <ResponsiveContainer width="100%" height={270}>
        <AreaChart
          data={data}
          margin={{ top: 6, right: 12, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id="rt-grad-messages" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={MSG_COLOR} stopOpacity={0.32} />
              <stop offset="100%" stopColor={MSG_COLOR} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="rt-grad-edges" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={EDGE_COLOR} stopOpacity={0.26} />
              <stop offset="100%" stopColor={EDGE_COLOR} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            vertical={false}
            strokeDasharray="3 3"
            stroke={t.border}
          />
          <XAxis
            dataKey="round"
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
            allowDecimals={false}
            width={36}
          />
          <Tooltip
            contentStyle={tt.contentStyle}
            labelStyle={tt.labelStyle}
            itemStyle={tt.itemStyle}
            cursor={{ stroke: t.borderHi }}
          />
          <Area
            type="monotone"
            dataKey="Messages"
            stroke={MSG_COLOR}
            strokeWidth={2}
            fill="url(#rt-grad-messages)"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
          <Area
            type="monotone"
            dataKey="Active edges"
            stroke={EDGE_COLOR}
            strokeWidth={2}
            fill="url(#rt-grad-edges)"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </StatCard>
  );
}
