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
import { RoundsTimelineChart } from "@/components/statistics/rounds-timeline-chart";
import {
  MessageTypesChart,
  SummaryCards,
} from "@/components/statistics/summary-cards";
import { useStatistics } from "@/hooks/useStatistics";
import { fetchHistoryTrials } from "@/lib/api";
import { getTheme } from "@/lib/theme";
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
  return `${trial.id} - ${formatRunTimestamp(trial.createdAt)}`;
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
        gap: 6,
        minWidth: 0,
      }}
    >
      <span style={{ color: t.textSub, fontSize: 11, fontWeight: 700 }}>
        {label}
      </span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={trials.length === 0}
        style={{
          background: t.surface,
          color: t.text,
          border: `1px solid ${t.border}`,
          borderRadius: 8,
          padding: "8px 10px",
          fontSize: 12,
          minWidth: 0,
          width: "100%",
        }}
      >
        {trials.length === 0 && (
          <option value="">
            {loading ? "Loading trials" : "No trials yet"}
          </option>
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
  const t = getTheme(dark);
  return (
    <section style={{ minWidth: 0 }}>
      <div
        style={{
          color: t.textSub,
          fontSize: 12,
          fontWeight: 800,
          marginBottom: 8,
          overflowWrap: "anywhere",
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
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h2
        style={{
          color: t.text,
          fontSize: 14,
          fontWeight: 800,
          margin: 0,
        }}
      >
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
          background: t.surface,
          border: `1px solid ${t.border}`,
          borderRadius: 8,
          color: t.textSub,
          padding: 18,
          minHeight: 120,
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
  const t = getTheme(dark);
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
          marginBottom: 18,
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

      {(first.loading || second.loading) && (
        <div style={{ color: t.textSub }}>Loading...</div>
      )}
      {(first.error || second.error) && (
        <div style={{ color: "#c2596d" }}>{first.error ?? second.error}</div>
      )}
      {!trialsLoading && trials.length < 2 && (
        <div style={{ color: t.textSub }}>
          Create at least two runs to compare different results.
        </div>
      )}

      {ready && first.summary && second.summary && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
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
