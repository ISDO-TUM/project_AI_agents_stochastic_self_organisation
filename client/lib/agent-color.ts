/**
 * 7 distinct non-burgundy, non-gold accents — one per agent slot when the
 * swarm has ≤7 agents. The market maker always renders burgundy
 * independently of this table; gold is reserved for promoted agents (see
 * PROMOTED_GOLD below), never assigned as a regular slot.
 */
const PALETTE = [
  "#3dba8c", // teal
  "#7b9ec0", // steel blue
  "#9b7bc0", // violet
  "#d97757", // coral
  "#5fb8d9", // cyan
  "#a3c26a", // sage-lime
  "#b07a9e", // dusty mauve (7th slot, replaces the old gold slot)
];

/** Burgundy — used for ALL agents once the swarm exceeds 7 participants. */
const BURG_ALL = "#C4374F";

/** Reserved for agents with at least one promoted draft entry — never part
 *  of the regular per-agent palette. */
export const PROMOTED_GOLD = "#b5860d";

/**
 * Returns the accent color for a given agent.
 *
 * Rules:
 *  - If the agent is in `promotedAgentIds`: always gold, regardless of swarm
 *    size — this takes priority over everything else below.
 *  - If `agents` is supplied and `agents.length >= 8`: every other agent
 *    renders burgundy so the swarm reads as a unified mass.
 *  - If `agents` is supplied and the agent is found in it: the agent gets the
 *    palette slot that matches its ordinal position (no hash collisions).
 *  - Fallback (no agents list, or agent not in list): deterministic hash so
 *    blackboard cards still get a stable colour without needing the full list.
 */
export function agentColor(
  agentId: string,
  agents: { id: string }[] = [],
  promotedAgentIds?: Set<string>,
): string {
  if (promotedAgentIds?.has(agentId)) return PROMOTED_GOLD;
  if (agents.length >= 8) return BURG_ALL;
  if (agents.length > 0) {
    const idx = agents.findIndex((a) => a.id === agentId);
    if (idx !== -1) return PALETTE[idx % PALETTE.length];
  }
  // Hash fallback — keeps colours stable in contexts without the agents list.
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = (hash * 31 + agentId.charCodeAt(i)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length];
}
