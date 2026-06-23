import { useEffect, useState } from "react";
import {
  fetchExperimentAgentStats,
  fetchExperimentEdgeStats,
  fetchExperimentLangfuseStats,
  fetchExperimentRoundStats,
  fetchExperimentSummary,
} from "@/lib/api";
import type {
  AgentStat,
  EdgeStat,
  ExperimentSummary,
  LangfuseStats,
  RoundStat,
} from "@/lib/types";

export interface StatisticsData {
  summary: ExperimentSummary | null;
  agents: AgentStat[];
  edges: EdgeStat[];
  rounds: RoundStat[];
  langfuse: LangfuseStats | null;
}

export interface UseStatisticsResult extends StatisticsData {
  loading: boolean;
  error: string | null;
}

const EMPTY: StatisticsData = {
  summary: null,
  agents: [],
  edges: [],
  rounds: [],
  langfuse: null,
};

interface StatisticsState extends StatisticsData {
  experimentId: string | null;
  error: string | null;
}

export function useStatistics(
  experimentId: string | null,
): UseStatisticsResult {
  const [state, setState] = useState<StatisticsState>({
    ...EMPTY,
    experimentId: null,
    error: null,
  });

  useEffect(() => {
    if (!experimentId) return;

    let cancelled = false;

    Promise.all([
      fetchExperimentSummary(experimentId),
      fetchExperimentAgentStats(experimentId),
      fetchExperimentEdgeStats(experimentId),
      fetchExperimentRoundStats(experimentId),
      fetchExperimentLangfuseStats(experimentId),
    ])
      .then(([summary, expAgents, expEdges, expRounds, expLangfuse]) => {
        if (cancelled) return;

        const agents: AgentStat[] = expAgents.map((a) => ({
          agentId: a.agentId,
          agentName: a.agentName,
          messagesSent: a.avgMessagesSent,
          messagesReceived: a.avgMessagesReceived,
          outDegree: a.avgOutDegree,
          inDegree: a.avgInDegree,
          toolInvocations: a.avgToolInvocations,
        }));

        const edges: EdgeStat[] = expEdges.map((e) => ({
          fromAgentId: e.fromAgentId,
          fromAgentName: e.fromAgentName,
          toAgentId: e.toAgentId,
          toAgentName: e.toAgentName,
          messageCount: e.avgMessageCount,
        }));

        // Give each averaged round a synthetic round_id using index
        const rounds: RoundStat[] = expRounds.map((r, i) => ({
          roundId: i,
          roundIndex: r.roundIndex,
          phase: r.phase,
          messageCount: r.avgMessageCount,
          activeEdgeCount: r.avgActiveEdgeCount,
        }));

        // Map experiment langfuse summary to the LangfuseStats shape (trial-scoped)
        const langfuse: LangfuseStats = {
          summary: {
            trialId: experimentId,
            traceCount: expLangfuse.summary.traceCount,
            generationCount: expLangfuse.summary.generationCount,
            inputTokens: expLangfuse.summary.inputTokens,
            outputTokens: expLangfuse.summary.outputTokens,
            totalTokens: expLangfuse.summary.totalTokens,
            totalCost: expLangfuse.summary.totalCost,
            averageLatencyMs: expLangfuse.summary.averageLatencyMs,
            slowestAgentName: expLangfuse.summary.slowestAgentName,
            slowestModel: expLangfuse.summary.slowestModel,
          },
          agents: expLangfuse.agents,
          models: expLangfuse.models,
          rounds: expLangfuse.rounds,
          available: expLangfuse.available,
          message: expLangfuse.message,
        };

        setState({
          experimentId,
          summary,
          agents,
          edges,
          rounds,
          langfuse,
          error: null,
        });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setState({
          ...EMPTY,
          experimentId,
          error: e instanceof Error ? e.message : "Failed to load statistics.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  if (!experimentId) return { ...EMPTY, loading: false, error: null };
  if (state.experimentId !== experimentId) {
    return { ...EMPTY, loading: true, error: null };
  }
  return {
    summary: state.summary,
    agents: state.agents,
    edges: state.edges,
    rounds: state.rounds,
    langfuse: state.langfuse,
    loading: false,
    error: state.error,
  };
}
