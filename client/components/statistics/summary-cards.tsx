"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import {
  CHART_COLORS,
  ENTRANCE,
  Kpi,
  MetaChip,
  MONO,
  StatCard,
  cardSurface,
  chartTooltipProps,
  labelStyle,
} from "@/components/statistics/primitives";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_DIM, getTheme } from "@/lib/theme";
import type { ExperimentSummary } from "@/lib/types";

function formatMode(mode: string | null) {
  if (!mode) return "Unknown";
  return mode
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatCreatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function SummaryCards({
  summary,
  dark,
  delay = 0,
}: {
  summary: ExperimentSummary;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <section
        style={{
          ...cardSurface(dark),
          padding: "18px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
          animation: ENTRANCE,
          animationDelay: `${delay}ms`,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: 7,
              background: BURG_DIM,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <LIcon name="Quote" size={13} color={BURG} />
          </div>
          <span style={{ ...labelStyle(dark), color: t.textSub }}>Prompt</span>
          <div
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
            }}
          >
            <MetaChip icon="FlaskConical" dark={dark}>
              {summary.trialCount} run{summary.trialCount === 1 ? "" : "s"}
            </MetaChip>
          </div>
        </div>
        <div
          style={{
            color: t.text,
            fontSize: 15.5,
            fontWeight: 650,
            lineHeight: 1.45,
            overflowWrap: "anywhere",
          }}
        >
          {summary.userPrompt}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <MetaChip icon="GitMerge" dark={dark}>
            Convergence: {formatMode(summary.mode)}
          </MetaChip>
          <span
            style={{
              color: t.textDim,
              fontSize: 10.5,
              fontFamily: MONO,
              overflowWrap: "anywhere",
            }}
          >
            {summary.experimentId}
          </span>
        </div>
      </section>

      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(140px, 100%), 1fr))",
          gap: 12,
        }}
      >
        <Kpi
          label="Avg Agents"
          icon="Users"
          value={Math.round(summary.avgAgentCount)}
          dark={dark}
          delay={delay + 40}
        />
        <Kpi
          label="Avg Rounds"
          icon="RotateCw"
          value={+summary.avgRoundCount.toFixed(1)}
          dark={dark}
          delay={delay + 80}
        />
        <Kpi
          label="Avg Messages"
          icon="MessageSquare"
          value={+summary.avgTotalMessages.toFixed(1)}
          dark={dark}
          delay={delay + 120}
        />
        <Kpi
          label="Avg Edges"
          icon="Waypoints"
          value={+summary.avgTotalEdges.toFixed(1)}
          dark={dark}
          delay={delay + 160}
        />
        <Kpi
          label="Runs"
          icon="CircleDot"
          value={summary.trialCount}
          dark={dark}
          delay={delay + 200}
        />
      </div>
    </div>
  );
}

export function MessageTypesChart({
  summary,
  dark,
  delay = 0,
}: {
  summary: ExperimentSummary;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  const tt = chartTooltipProps(dark);
  const sorted = Object.entries(summary.messageTypeCounts).sort(
    (a, b) => b[1] - a[1],
  );
  const pieData = sorted.map(([name, value]) => ({ name, value }));
  const total = pieData.reduce((sum, d) => sum + d.value, 0);

  return (
    <StatCard
      title="Message mix"
      icon="ChartPie"
      dark={dark}
      delay={delay}
      minHeight={280}
      meta={
        <span style={{ color: t.textDim, fontSize: 11, fontFamily: MONO }}>
          {sorted.length} types
        </span>
      }
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          flexWrap: "wrap",
          height: "100%",
        }}
      >
        <div
          style={{
            position: "relative",
            width: 176,
            height: 176,
            flexShrink: 0,
            margin: "0 auto",
          }}
        >
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                innerRadius={58}
                outerRadius={84}
                paddingAngle={2}
                cornerRadius={3}
                stroke="none"
              >
                {pieData.map((entry, i) => (
                  <Cell
                    key={entry.name}
                    fill={CHART_COLORS[i % CHART_COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={tt.contentStyle}
                labelStyle={tt.labelStyle}
                itemStyle={tt.itemStyle}
              />
            </PieChart>
          </ResponsiveContainer>
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              pointerEvents: "none",
            }}
          >
            <span
              style={{
                color: t.text,
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: -0.4,
              }}
            >
              {total}
            </span>
            <span style={labelStyle(dark)}>messages</span>
          </div>
        </div>

        <div
          style={{
            flex: 1,
            minWidth: 180,
            display: "flex",
            flexDirection: "column",
            gap: 9,
            maxHeight: 210,
            overflowY: "auto",
            paddingRight: 4,
          }}
        >
          {pieData.map((entry, i) => {
            const color = CHART_COLORS[i % CHART_COLORS.length];
            const pct = total > 0 ? Math.round((entry.value / total) * 100) : 0;
            return (
              <div
                key={entry.name}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  minWidth: 0,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 7,
                    fontSize: 11.5,
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: color,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      color: t.text,
                      fontWeight: 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {entry.name}
                  </span>
                  <span
                    style={{
                      marginLeft: "auto",
                      color: t.textSub,
                      fontVariantNumeric: "tabular-nums",
                      flexShrink: 0,
                    }}
                  >
                    {entry.value} · {pct}%
                  </span>
                </div>
                <div
                  style={{
                    height: 3,
                    borderRadius: 2,
                    background: t.inputBg,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${pct}%`,
                      height: "100%",
                      borderRadius: 2,
                      background: color,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </StatCard>
  );
}
