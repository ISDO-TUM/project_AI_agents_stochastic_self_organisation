"use client";

import { useEffect, useState } from "react";
import { AgentActivityChart } from "@/components/statistics/agent-activity-chart";
import { CommunicationGraph } from "@/components/statistics/communication-graph";
import {
  LlmRoundsChart,
  LlmUsageSummaryCards,
  PerAgentLlmUsageChart,
  TokensByModelChart,
} from "@/components/statistics/langfuse-observability";
import {
  EmptyState,
  SkeletonCard,
  cardSurface,
  labelStyle,
} from "@/components/statistics/primitives";
import { RoundsTimelineChart } from "@/components/statistics/rounds-timeline-chart";
import {
  MessageTypesChart,
  SummaryCards,
} from "@/components/statistics/summary-cards";
import { useStatistics } from "@/hooks/useStatistics";
import { fetchHistoryTrials } from "@/lib/api";
import { BURG, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import type { HistoryTrial, LangfuseStats } from "@/lib/types";

function formatRunTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatTrialOption(trial: HistoryTrial) {
  const label = trial.description?.trim() || trial.id;
  return `${label} · ${formatRunTimestamp(trial.createdAt)}`;
}

function RunSelect({
  label,
  value,
  trials,
  loading,
  onChange,
  dark,
}: {
  label: string;
  value: string | null;
  trials: HistoryTrial[];
  loading: boolean;
  onChange: (trialId: string | null) => void;
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <label
      style={{
        display: "flex",
        flex: "1 1 320px",
        flexDirection: "column",
        gap: 7,
        minWidth: 0,
      }}
    >
      <span style={labelStyle(dark)}>{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={trials.length === 0}
        style={{
          background: t.inputBg,
          color: t.text,
          border: `1.5px solid ${t.border}`,
          borderRadius: 10,
          padding: "9px 34px 9px 13px",
          fontSize: 12.5,
          fontWeight: 600,
          minWidth: 0,
          width: "100%",
          outline: "none",
          cursor: trials.length === 0 ? "not-allowed" : "pointer",
          appearance: "none",
          backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236B6880'/%3E%3C/svg%3E")`,
          backgroundRepeat: "no-repeat",
          backgroundPosition: "right 13px center",
        }}
      >
        {trials.length === 0 && (
          <option value="">{loading ? "Loading runs…" : "No runs yet"}</option>
        )}
        {trials.map((trial) => (
          <option key={trial.id} value={trial.id}>
            {formatTrialOption(trial)}
          </option>
        ))}
      </select>
    </label>
  );
}

function RunColumn({
  title,
  children,
  dark,
}: {
  title: string;
  children: React.ReactNode;
  dark: boolean;
}) {
  return (
    <section style={{ minWidth: 0 }}>
      <div
        style={{
          ...labelStyle(dark),
          whiteSpace: "normal",
          overflowWrap: "anywhere",
          marginBottom: 9,
        }}
      >
        {title}
      </div>
      {children}
    </section>
  );
}

function ComparisonRow({
  title,
  leftTitle,
  rightTitle,
  left,
  right,
  dark,
}: {
  title: string;
  leftTitle: string;
  rightTitle: string;
  left: React.ReactNode;
  right: React.ReactNode;
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h2
        style={{
          display: "flex",
          alignItems: "center",
          gap: 9,
          color: t.text,
          fontSize: 13.5,
          fontWeight: 800,
          letterSpacing: 0.3,
          margin: 0,
        }}
      >
        <span
          style={{
            width: 3,
            height: 15,
            borderRadius: 2,
            background: BURG,
            boxShadow: "0 0 8px rgba(139,26,47,0.5)",
            flexShrink: 0,
          }}
        />
        {title}
      </h2>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(360px, 1fr))",
          gap: 16,
          overflowX: "auto",
        }}
      >
        <RunColumn title={leftTitle} dark={dark}>
          {left}
        </RunColumn>
        <RunColumn title={rightTitle} dark={dark}>
          {right}
        </RunColumn>
      </div>
    </div>
  );
}

function LlmSlot({
  langfuse,
  dark,
  children,
}: {
  langfuse: LangfuseStats | null;
  dark: boolean;
  children: (langfuse: LangfuseStats) => React.ReactNode;
}) {
  const t = getTheme(dark);
  if (!langfuse?.available) {
    return (
      <div
        style={{
          ...cardSurface(dark),
          color: t.textSub,
          fontSize: 12.5,
          lineHeight: 1.6,
          padding: 18,
          minHeight: 120,
          display: "flex",
          alignItems: "center",
        }}
      >
        {langfuse?.message ?? "No LLM usage data is available for this run."}
      </div>
    );
  }
  return children(langfuse);
}

export function ComparisonDashboard() {
  const { dark } = useTheme();
  const [trials, setTrials] = useState<HistoryTrial[]>([]);
  const [firstTrialId, setFirstTrialId] = useState<string | null>(null);
  const [secondTrialId, setSecondTrialId] = useState<string | null>(null);
  const [trialsLoading, setTrialsLoading] = useState(true);
  const first = useStatistics(firstTrialId);
  const second = useStatistics(secondTrialId);

  useEffect(() => {
    fetchHistoryTrials()
      .then((rows) => {
        setTrials(rows);
        setFirstTrialId(rows[0]?.id ?? null);
        setSecondTrialId(rows[1]?.id ?? rows[0]?.id ?? null);
      })
      .catch(() => setTrials([]))
      .finally(() => setTrialsLoading(false));
  }, []);

  const ready =
    first.summary &&
    second.summary &&
    !first.loading &&
    !second.loading &&
    !first.error &&
    !second.error;

  const firstTitle = first.summary?.description ?? firstTrialId ?? "First run";
  const secondTitle =
    second.summary?.description ?? secondTrialId ?? "Second run";

  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: 14,
          margin: "10px 0 22px",
          flexWrap: "wrap",
        }}
      >
        <RunSelect
          label="First run"
          value={firstTrialId}
          trials={trials}
          loading={trialsLoading}
          onChange={setFirstTrialId}
          dark={dark}
        />
        <RunSelect
          label="Second run"
          value={secondTrialId}
          trials={trials}
          loading={trialsLoading}
          onChange={setSecondTrialId}
          dark={dark}
        />
      </div>

      {!trialsLoading && trials.length < 2 ? (
        <EmptyState
          icon="GitCompare"
          title="Not enough runs to compare"
          sub="Create at least two simulation runs to compare their results side by side."
          dark={dark}
        />
      ) : trialsLoading || first.loading || second.loading ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(360px, 1fr))",
            gap: 16,
            overflowX: "auto",
          }}
        >
          <SkeletonCard height={300} dark={dark} />
          <SkeletonCard height={300} dark={dark} delay={80} />
        </div>
      ) : first.error || second.error ? (
        <div style={{ color: "#c2596d", fontSize: 13, marginBottom: 16 }}>
          {first.error ?? second.error}
        </div>
      ) : null}

      {ready && first.summary && second.summary && (
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <ComparisonRow
            title="Fixed statistics"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={<SummaryCards summary={first.summary} dark={dark} />}
            right={<SummaryCards summary={second.summary} dark={dark} />}
            dark={dark}
          />
          <ComparisonRow
            title="Message types"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={<MessageTypesChart summary={first.summary} dark={dark} />}
            right={<MessageTypesChart summary={second.summary} dark={dark} />}
            dark={dark}
          />
          <ComparisonRow
            title="Communication graph"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={
              <CommunicationGraph
                agents={first.agents}
                edges={first.edges}
                dark={dark}
              />
            }
            right={
              <CommunicationGraph
                agents={second.agents}
                edges={second.edges}
                dark={dark}
              />
            }
            dark={dark}
          />
          <ComparisonRow
            title="Per-agent activity"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={<AgentActivityChart agents={first.agents} dark={dark} />}
            right={<AgentActivityChart agents={second.agents} dark={dark} />}
            dark={dark}
          />
          <ComparisonRow
            title="Self-organisation over rounds"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={<RoundsTimelineChart rounds={first.rounds} dark={dark} />}
            right={<RoundsTimelineChart rounds={second.rounds} dark={dark} />}
            dark={dark}
          />
          <ComparisonRow
            title="LLM usage summary"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={
              <LlmSlot langfuse={first.langfuse} dark={dark}>
                {(langfuse) => (
                  <LlmUsageSummaryCards langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            right={
              <LlmSlot langfuse={second.langfuse} dark={dark}>
                {(langfuse) => (
                  <LlmUsageSummaryCards langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            dark={dark}
          />
          <ComparisonRow
            title="Tokens by model"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={
              <LlmSlot langfuse={first.langfuse} dark={dark}>
                {(langfuse) => (
                  <TokensByModelChart langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            right={
              <LlmSlot langfuse={second.langfuse} dark={dark}>
                {(langfuse) => (
                  <TokensByModelChart langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            dark={dark}
          />
          <ComparisonRow
            title="Per-agent LLM usage"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={
              <LlmSlot langfuse={first.langfuse} dark={dark}>
                {(langfuse) => (
                  <PerAgentLlmUsageChart langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            right={
              <LlmSlot langfuse={second.langfuse} dark={dark}>
                {(langfuse) => (
                  <PerAgentLlmUsageChart langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            dark={dark}
          />
          <ComparisonRow
            title="Cost and tokens over rounds"
            leftTitle={firstTitle}
            rightTitle={secondTitle}
            left={
              <LlmSlot langfuse={first.langfuse} dark={dark}>
                {(langfuse) => (
                  <LlmRoundsChart langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            right={
              <LlmSlot langfuse={second.langfuse} dark={dark}>
                {(langfuse) => (
                  <LlmRoundsChart langfuse={langfuse} dark={dark} />
                )}
              </LlmSlot>
            }
            dark={dark}
          />
        </div>
      )}
    </div>
  );
}
