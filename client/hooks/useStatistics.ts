import { useEffect, useState } from "react";
import {
  fetchAgentStats,
  fetchEdgeStats,
  fetchLangfuseStats,
  fetchRoundStats,
  fetchTrialSummary,
} from "@/lib/api";
import type {
  AgentStat,
  EdgeStat,
  LangfuseStats,
  RoundStat,
  TrialSummary,
} from "@/lib/types";

export interface StatisticsData {
  summary: TrialSummary | null;
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
  trialId: string | null;
  error: string | null;
}

export function useStatistics(trialId: string | null): UseStatisticsResult {
  const [state, setState] = useState<StatisticsState>({
    ...EMPTY,
    trialId: null,
    error: null,
  });

  useEffect(() => {
    if (!trialId) return;

    let cancelled = false;

    Promise.all([
      fetchTrialSummary(trialId),
      fetchAgentStats(trialId),
      fetchEdgeStats(trialId),
      fetchRoundStats(trialId),
      fetchLangfuseStats(trialId),
    ])
      .then(([summary, agents, edges, rounds, langfuse]) => {
        if (!cancelled) {
          setState({
            trialId,
            summary,
            agents,
            edges,
            rounds,
            langfuse,
            error: null,
          });
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setState({
          ...EMPTY,
          trialId,
          error: e instanceof Error ? e.message : "Failed to load statistics.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [trialId]);

  if (!trialId) return { ...EMPTY, loading: false, error: null };
  if (state.trialId !== trialId) {
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
