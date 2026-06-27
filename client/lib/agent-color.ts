/**
 * 7 distinct non-burgundy accents — one per agent slot when the swarm has ≤7
 * agents. The market maker always renders burgundy independently of this table.
 */
const PALETTE = [
  "#3dba8c", // teal
  "#b5860d", // gold
  "#7b9ec0", // steel blue
  "#9b7bc0", // violet
  "#d97757", // coral
  "#5fb8d9", // cyan
  "#a3c26a", // sage-lime (7th slot)
];

/** Burgundy — used for ALL agents once the swarm exceeds 7 participants. */
const BURG_ALL = "#C4374F";

/**
 * Returns the accent color for a given agent.
 *
 * Rules:
 *  - If `agents` is supplied and `agents.length >= 8`: every agent renders
 *    burgundy so the swarm reads as a unified mass.
 *  - If `agents` is supplied and the agent is found in it: the agent gets the
 *    palette slot that matches its ordinal position (no hash collisions).
 *  - Fallback (no agents list, or agent not in list): deterministic hash so
 *    blackboard cards still get a stable colour without needing the full list.
 */
export function agentColor(
  agentId: string,
  agents: { id: string }[] = [],
): string {
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
