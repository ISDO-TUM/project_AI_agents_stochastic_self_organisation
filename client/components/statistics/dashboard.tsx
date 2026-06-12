"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ComparisonDashboard } from "@/components/comparison/dashboard";
import { AgentActivityChart } from "@/components/statistics/agent-activity-chart";
import { CommunicationGraph } from "@/components/statistics/communication-graph";
import { LangfuseObservability } from "@/components/statistics/langfuse-observability";
import {
  EmptyState,
  ErrorState,
  SkeletonCard,
  labelStyle,
} from "@/components/statistics/primitives";
import { RoundsTimelineChart } from "@/components/statistics/rounds-timeline-chart";
import {
  MessageTypesChart,
  SummaryCards,
} from "@/components/statistics/summary-cards";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useStatistics } from "@/hooks/useStatistics";
import { fetchExperiments } from "@/lib/api";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_DIM, BURG_LT, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import type { ExperimentListItem } from "@/lib/types";

type ViewId = "collaboration" | "langfuse" | "comparison";

const VIEWS: { id: ViewId; label: string; icon: string }[] = [
  { id: "collaboration", label: "Collaboration", icon: "Network" },
  { id: "langfuse", label: "LLM usage", icon: "Cpu" },
  { id: "comparison", label: "Comparison", icon: "GitCompare" },
];

function formatRunTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatExperimentOption(exp: ExperimentListItem) {
  const label = exp.description?.trim() || exp.id;
  const runs = `${exp.trialCount} run${exp.trialCount === 1 ? "" : "s"}`;
  return `${label} · ${runs} · ${formatRunTimestamp(exp.createdAt)}`;
}

function Sep({ t }: { t: ReturnType<typeof getTheme> }) {
  return (
    <div
      style={{ width: 1, height: 18, background: t.border, margin: "0 3px" }}
    />
  );
}

function HeaderLink({
  href,
  icon,
  children,
  t,
}: {
  href: string;
  icon: string;
  children: React.ReactNode;
  t: ReturnType<typeof getTheme>;
}) {
  const [hov, setHov] = useState(false);
  return (
    <Link
      href={href}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: hov ? t.hover : "transparent",
        borderRadius: 8,
        color: hov ? t.text : t.textSub,
        fontSize: 12,
        fontWeight: 600,
        padding: "6px 11px",
        display: "flex",
        alignItems: "center",
        gap: 6,
        transition: "all 0.15s",
        whiteSpace: "nowrap",
        textDecoration: "none",
      }}
    >
      <LIcon name={icon} size={14} color="currentColor" />
      {children}
    </Link>
  );
}

function ViewSwitch({
  view,
  onChange,
  t,
}: {
  view: ViewId;
  onChange: (view: ViewId) => void;
  t: ReturnType<typeof getTheme>;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: t.inputBg,
        border: `1px solid ${t.border}`,
        borderRadius: 100,
        padding: 3,
      }}
    >
      {VIEWS.map(({ id, label, icon }) => {
        const active = view === id;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              background: active ? "rgba(139,26,47,0.2)" : "transparent",
              border: "none",
              borderRadius: 100,
              color: active ? t.text : t.textSub,
              boxShadow: active ? "0 0 12px rgba(139,26,47,0.2)" : "none",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 700,
              padding: "5px 12px",
              transition: "all 0.15s",
              whiteSpace: "nowrap",
            }}
          >
            <LIcon
              name={icon}
              size={13}
              color={active ? BURG_LT : "currentColor"}
            />
            {label}
          </button>
        );
      })}
    </div>
  );
}

function LoadingSkeleton({ dark }: { dark: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SkeletonCard height={124} dark={dark} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(150px, 100%), 1fr))",
          gap: 12,
        }}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <SkeletonCard
            key={i}
            height={82}
            dark={dark}
            delay={i * 50}
            radius={12}
          />
        ))}
      </div>
      <SkeletonCard height={320} dark={dark} delay={280} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(420px, 100%), 1fr))",
          gap: 16,
        }}
      >
        <SkeletonCard height={300} dark={dark} delay={340} />
        <SkeletonCard height={300} dark={dark} delay={400} />
      </div>
    </div>
  );
}

export function StatisticsDashboard() {
  const { dark, toggle } = useTheme();
  const t = getTheme(dark);
  const [experiments, setExperiments] = useState<ExperimentListItem[]>([]);
  const [experimentId, setExperimentId] = useState<string | null>(null);
  const [experimentsLoading, setExperimentsLoading] = useState(true);
  const [view, setView] = useState<ViewId>("collaboration");
  const stats = useStatistics(experimentId);

  useEffect(() => {
    fetchExperiments()
      .then((rows) => {
        setExperiments(rows);
        if (rows.length > 0) setExperimentId(rows[0].id);
      })
      .catch(() => setExperiments([]))
      .finally(() => setExperimentsLoading(false));
  }, []);

  const noExperiments = !experimentsLoading && experiments.length === 0;
  const loading = experimentsLoading || stats.loading;

  return (
    <main
      style={{
        background: dark
          ? "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.07) 0%, transparent 70%), #060608"
          : "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.04) 0%, transparent 70%), #f0eef8",
        color: t.text,
        height: "100vh",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          overflowY: "auto",
          overscrollBehavior: "contain",
          scrollbarGutter: "stable",
          padding: "0 24px 56px",
        }}
      >
        {/* floating pill header, matching the canvas toolbar */}
        <div
          style={{
            position: "sticky",
            top: 0,
            zIndex: 100,
            display: "flex",
            justifyContent: "center",
            padding: "16px 0 14px",
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "8px 14px",
              background: t.pill,
              backdropFilter: "blur(28px)",
              WebkitBackdropFilter: "blur(28px)",
              border: `1px solid ${t.pillBorder}`,
              borderRadius: 100,
              pointerEvents: "all",
              flexWrap: "wrap",
              justifyContent: "center",
              animation: `${
                dark ? "pillPulse" : "pillPulseLight"
              } 4s ease-in-out infinite`,
              boxShadow: dark
                ? "0 0 0 1px rgba(139,26,47,0.14), 0 4px 20px rgba(139,26,47,0.12), 0 8px 36px rgba(0,0,0,0.35)"
                : "0 0 0 1px rgba(139,26,47,0.10), 0 4px 18px rgba(139,26,47,0.10), 0 6px 24px rgba(0,0,0,0.07)",
            }}
          >
            <HeaderLink href="/" icon="ArrowLeft" t={t}>
              Canvas
            </HeaderLink>

            <Sep t={t} />

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "0 8px",
              }}
            >
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 8,
                  background: BURG_DIM,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <LIcon name="ChartNoAxesColumn" size={14} color={BURG} />
              </div>
              <span
                style={{
                  fontWeight: 700,
                  fontSize: 13.5,
                  color: t.text,
                  letterSpacing: 0.4,
                }}
              >
                Statistics
              </span>
            </div>

            <Sep t={t} />

            <ViewSwitch view={view} onChange={setView} t={t} />

            <Sep t={t} />

            <button
              onClick={toggle}
              title="Toggle theme"
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: t.textSub,
                padding: "5px 7px",
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) =>
                ((e.currentTarget as HTMLButtonElement).style.color = t.text)
              }
              onMouseLeave={(e) =>
                ((e.currentTarget as HTMLButtonElement).style.color = t.textSub)
              }
            >
              <LIcon
                name={dark ? "Sun" : "Moon"}
                size={15}
                color="currentColor"
              />
            </button>
          </div>
        </div>

        <div style={{ maxWidth: 1340, margin: "0 auto" }}>
          {view !== "comparison" && !noExperiments && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                margin: "10px 0 18px",
                flexWrap: "wrap",
              }}
            >
              <span style={labelStyle(dark)}>Experiment</span>
              <Select
                value={experimentId ?? ""}
                onValueChange={(value) => setExperimentId(value || null)}
              >
                <SelectTrigger disabled={experiments.length === 0}>
                  <span
                    style={{
                      maxWidth: "min(48vw, 440px)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      display: "block",
                    }}
                  >
                    <SelectValue
                      placeholder={
                        experimentsLoading
                          ? "Loading experiments…"
                          : "No experiments yet"
                      }
                    />
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {experiments.map((exp) => (
                    <SelectItem key={exp.id} value={exp.id}>
                      <span
                        style={{
                          maxWidth: "min(70vw, 480px)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          display: "block",
                        }}
                      >
                        {formatExperimentOption(exp)}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span
                style={{
                  ...labelStyle(dark),
                  marginLeft: "auto",
                  letterSpacing: 0.8,
                }}
              >
                {experiments.length} experiment
                {experiments.length === 1 ? "" : "s"} recorded
              </span>
            </div>
          )}

          {view === "comparison" ? (
            <ComparisonDashboard />
          ) : noExperiments ? (
            <EmptyState
              icon="ChartNoAxesColumn"
              title="No simulation data yet"
              sub="Run a simulation on the canvas and its collaboration analytics, LLM usage and round-by-round dynamics will show up here."
              dark={dark}
              action={
                <Link
                  href="/"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 7,
                    background: BURG,
                    color: "#fff",
                    borderRadius: 10,
                    fontSize: 13,
                    fontWeight: 600,
                    padding: "10px 18px",
                    textDecoration: "none",
                    boxShadow: "0 2px 12px rgba(139,26,47,0.22)",
                  }}
                >
                  <LIcon name="ArrowLeft" size={14} color="currentColor" />
                  Back to canvas
                </Link>
              }
            />
          ) : loading ? (
            <LoadingSkeleton dark={dark} />
          ) : stats.error ? (
            <ErrorState message={stats.error} dark={dark} />
          ) : view === "collaboration" && stats.summary ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <SummaryCards summary={stats.summary} dark={dark} />
              <RoundsTimelineChart
                rounds={stats.rounds}
                dark={dark}
                delay={240}
              />
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "repeat(auto-fit, minmax(min(420px, 100%), 1fr))",
                  gap: 16,
                  alignItems: "stretch",
                }}
              >
                <MessageTypesChart
                  summary={stats.summary}
                  dark={dark}
                  delay={300}
                />
                <CommunicationGraph
                  agents={stats.agents}
                  edges={stats.edges}
                  dark={dark}
                  delay={360}
                />
              </div>
              <AgentActivityChart
                agents={stats.agents}
                dark={dark}
                delay={420}
              />
            </div>
          ) : view === "langfuse" && stats.langfuse ? (
            <LangfuseObservability langfuse={stats.langfuse} dark={dark} />
          ) : null}
        </div>
      </div>
    </main>
  );
}
