export type ReasoningEffort = "low" | "high";

export interface SwarmRunConfig {
  takersMin: number;
  takersMax: number;
  roundsMin: number;
  roundsMax: number;
  tokenBudget: number;
  maxAmendments: number;
  inviteFloor: number;
  decayRounds: number;
  reasoningEffort: ReasoningEffort;
}

export const DEFAULT_SWARM_CONFIG: SwarmRunConfig = {
  takersMin: 2,
  takersMax: 5,
  roundsMin: 2,
  roundsMax: 10,
  tokenBudget: 50000,
  maxAmendments: 2,
  inviteFloor: 0.3,
  decayRounds: 3,
  reasoningEffort: "high",
};
