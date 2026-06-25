const PALETTE = [
  "#C4374F", // burgundy-light
  "#3dba8c", // teal
  "#b5860d", // gold
  "#7b9ec0", // steel blue
  "#9b7bc0", // violet
  "#d97757", // coral
  "#5fb8d9", // cyan
];

/** Deterministic per-agent color so the same agent always renders the same
 *  accent across the canvas node, blackboard posts, and reply threads. */
export function agentColor(agentId: string): string {
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = (hash * 31 + agentId.charCodeAt(i)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length];
}
