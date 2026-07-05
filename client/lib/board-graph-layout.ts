/**
 * Pure, framework-agnostic layout engine for the draft board's "graph view".
 *
 * Concept ("orbit" layout): every agent gets a hub anchored on a circle
 * around the board's center. Their contributions spiral outward from their
 * own hub inside a private angular wedge, so — by construction — one
 * agent's cards can never drift into another agent's territory. A cheap
 * AABB relaxation pass then irons out any local overlaps caused by
 * variable card heights (long vs. short content). The result: a layout
 * that is deterministic, cheap to recompute, and guaranteed overlap-free
 * for realistic board sizes.
 *
 * "Gravity" is used as the organizing metaphor: entries that were
 * confirmed (crossed the citation threshold) get pulled in toward the
 * shared center — literally closer to consensus — while evaporated
 * entries drift further out.
 */
import { Citer, DraftEntry } from "./types";
import { truncate } from "./blackboard-utils";
import { agentColor } from "./agent-color";

// ─── Flattening ──────────────────────────────────────────────────────────

export interface FlatEntry {
  id: string;
  author_id: string;
  author_name: string;
  entry_type: DraftEntry["entry_type"];
  content: string;
  round: number;
  reply_to: string | null;
  mention_agents: string[];
  is_visible: boolean;
  citation_count: number;
  citers?: Citer[];
  created_at: string;
  parentId: string | null;
  depth: number;
}

export function flattenDraftEntries(draft: DraftEntry[]): FlatEntry[] {
  const out: FlatEntry[] = [];
  const walk = (entries: DraftEntry[], depth: number) => {
    for (const e of entries) {
      out.push({
        id: e.id,
        author_id: e.author_id,
        author_name: e.author_name,
        entry_type: e.entry_type,
        content: e.content,
        round: e.round,
        reply_to: e.reply_to,
        mention_agents: e.mention_agents,
        is_visible: e.is_visible,
        citation_count: e.citation_count,
        citers: e.citers,
        created_at: e.created_at,
        parentId: e.reply_to,
        depth,
      });
      if (e.children.length) walk(e.children, depth + 1);
    }
  };
  walk(draft, 0);
  return out;
}

// ─── Layout types ────────────────────────────────────────────────────────

export interface GraphAgentHub {
  id: string;
  name: string;
  x: number;
  y: number;
  angle: number;
  entryCount: number;
  visibleCount: number;
  citationTotal: number;
  confirmedCount: number;
  /** Citations this agent gave to *other* agents' entries — the only
   *  signal available for agents who never authored anything themselves
   *  (pure voters/citers), so they still register as participants. */
  citesGiven: number;
}

export interface GraphEntryNode {
  entry: FlatEntry;
  /** top-left, world space */
  x: number;
  y: number;
  w: number;
  h: number;
  confirmedRound: number | null;
  /** true = renders as a small pill (declutter tiering, proposal/reply only).
   *  Decided once per layout by significance tiering below the density gate;
   *  votes/system entries are already pill-styled by type and stay `false`. */
  compact: boolean;
}

export interface GraphLayout {
  hubs: GraphAgentHub[];
  nodes: GraphEntryNode[];
  nodeById: Map<string, GraphEntryNode>;
  hubById: Map<string, GraphAgentHub>;
  /** Resolves a citer's display name back to an agent id — built once from
   *  the full agent roster so it works even for agents with zero authored
   *  entries. Reused by `buildGraphEdges` instead of re-derived. */
  nameToId: Map<string, string>;
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export const HUB_RADIUS = 28;

const LANE_W = 230;
const LANE_GUTTER = 54;
const START_GAP = 70;
const SPACING_R = 40;
/** Every agent's angular wedge is proportional to `max(entryCount, MIN_WEIGHT)`
 *  out of the shared 2π ring — prolific agents get a wide slice to spiral
 *  in, quiet/citer-only agents still get a small, non-crowded sliver. */
const MIN_WEIGHT = 2.2;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const MAX_RELAX_ENTRIES = 320;
const MAX_RELAX_ITERATIONS = 60;

function estimateCardSize(
  entry: FlatEntry,
  compact = false,
): { w: number; h: number } {
  if (compact && (entry.entry_type === "proposal" || entry.entry_type === "reply")) {
    return { w: 170, h: 30 };
  }
  if (entry.entry_type === "vote") return { w: 160, h: 36 };
  if (entry.entry_type === "system") return { w: 184, h: 30 };
  const w = entry.entry_type === "proposal" ? 240 : 214;
  const preview = truncate(entry.content, 128);
  const charsPerLine = entry.entry_type === "proposal" ? 29 : 26;
  const lines = Math.max(1, Math.ceil(preview.length / charsPerLine));
  const base = entry.entry_type === "proposal" ? 58 : 50;
  const h = base + lines * 14;
  return { w, h: Math.min(148, Math.max(base + 14, h)) };
}

function relaxCollisions(nodes: GraphEntryNode[], hubs: GraphAgentHub[]): void {
  const n = nodes.length;
  if (n === 0 || n > MAX_RELAX_ENTRIES) return;
  const padding = 10;

  for (let iter = 0; iter < MAX_RELAX_ITERATIONS; iter++) {
    let moved = false;

    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const ax0 = a.x - padding / 2;
        const ay0 = a.y - padding / 2;
        const ax1 = a.x + a.w + padding / 2;
        const ay1 = a.y + a.h + padding / 2;
        const bx0 = b.x - padding / 2;
        const by0 = b.y - padding / 2;
        const bx1 = b.x + b.w + padding / 2;
        const by1 = b.y + b.h + padding / 2;
        const overlapX = Math.min(ax1, bx1) - Math.max(ax0, bx0);
        const overlapY = Math.min(ay1, by1) - Math.max(ay0, by0);
        if (overlapX > 0 && overlapY > 0) {
          moved = true;
          if (overlapX < overlapY) {
            const push = overlapX / 2 + 0.5;
            if (a.x < b.x) {
              a.x -= push;
              b.x += push;
            } else {
              a.x += push;
              b.x -= push;
            }
          } else {
            const push = overlapY / 2 + 0.5;
            if (a.y < b.y) {
              a.y -= push;
              b.y += push;
            } else {
              a.y += push;
              b.y -= push;
            }
          }
        }
      }
    }

    for (const node of nodes) {
      for (const hub of hubs) {
        const ncx = node.x + node.w / 2;
        const ncy = node.y + node.h / 2;
        const dx = ncx - hub.x;
        const dy = ncy - hub.y;
        const dist = Math.hypot(dx, dy) || 0.001;
        const minDist = HUB_RADIUS + Math.max(node.w, node.h) / 2 + 26;
        if (dist < minDist) {
          moved = true;
          const push = minDist - dist;
          const ux = dx / dist;
          const uy = dy / dist;
          node.x += ux * push;
          node.y += uy * push;
        }
      }
    }

    if (!moved) break;
  }
}

/**
 * Post-clamp mop-up: pushes any two cards from the *same* agent further
 * apart along their own current radius (never sideways) if they still
 * overlap. Only needed because the angular-containment clamp in
 * `computeBoardGraphLayout` can occasionally re-introduce an overlap that
 * `relaxCollisions` had resolved mostly by moving a card sideways — since
 * this only ever increases radius, a card can never escape the wedge the
 * clamp just enforced.
 */
function relaxSameAuthorRadially(nodes: GraphEntryNode[]): void {
  const n = nodes.length;
  if (n === 0 || n > MAX_RELAX_ENTRIES) return;
  const padding = 10;

  for (let iter = 0; iter < 20; iter++) {
    let moved = false;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i];
        const b = nodes[j];
        if (a.entry.author_id !== b.entry.author_id) continue;
        const overlapX =
          Math.min(a.x + a.w + padding / 2, b.x + b.w + padding / 2) -
          Math.max(a.x - padding / 2, b.x - padding / 2);
        const overlapY =
          Math.min(a.y + a.h + padding / 2, b.y + b.h + padding / 2) -
          Math.max(a.y - padding / 2, b.y - padding / 2);
        if (overlapX > 0 && overlapY > 0) {
          moved = true;
          const push = Math.min(overlapX, overlapY) / 2 + 3;
          for (const node of [a, b]) {
            const cx = node.x + node.w / 2;
            const cy = node.y + node.h / 2;
            const r = Math.hypot(cx, cy) || 0.001;
            const ang = Math.atan2(cy, cx);
            const nr = r + push;
            node.x = nr * Math.cos(ang) - node.w / 2;
            node.y = nr * Math.sin(ang) - node.h / 2;
          }
        }
      }
    }
    if (!moved) break;
  }
}

/**
 * Computes the full "orbit" layout for a (possibly thread-filtered) draft
 * tree. `agentOrder` should be the canvas agents list (for stable hub
 * ordering + color parity with the rest of the app); any author id not
 * present in it (e.g. a system author) is appended deterministically.
 * `promotedMap` mirrors DraftBoard's `source_draft_id -> round_confirmed`.
 */
export function computeBoardGraphLayout(
  draft: DraftEntry[],
  agents: { id: string; name?: string }[],
  promotedMap: Map<string, number>,
): GraphLayout {
  const flat = flattenDraftEntries(draft).sort((a, b) => {
    if (a.round !== b.round) return a.round - b.round;
    return a.created_at.localeCompare(b.created_at);
  });

  // ── Significance tiering (proposal/reply only) ──────────────────────────
  // ≤ FULL_CARD_LIMIT such entries: everything renders full (density gate).
  // Above it: confirmed entries are always full; remaining full slots go to
  // the highest-cited (tie: earliest) until the limit; the rest are pills.
  // Nothing is ever hidden — pills are smaller, not absent.
  const tierable = flat.filter(
    (e) => e.entry_type === "proposal" || e.entry_type === "reply",
  );
  const compactIds = new Set<string>();
  if (tierable.length > FULL_CARD_LIMIT) {
    const confirmed = tierable.filter((e) => promotedMap.has(e.id));
    const rest = tierable
      .filter((e) => !promotedMap.has(e.id))
      .sort((a, b) =>
        a.citation_count !== b.citation_count
          ? b.citation_count - a.citation_count
          : a.created_at.localeCompare(b.created_at),
      );
    const fullSlotsLeft = Math.max(0, FULL_CARD_LIMIT - confirmed.length);
    for (const e of rest.slice(fullSlotsLeft)) compactIds.add(e.id);
  }

  const byAuthor = new Map<string, FlatEntry[]>();
  for (const e of flat) {
    const list = byAuthor.get(e.author_id);
    if (list) list.push(e);
    else byAuthor.set(e.author_id, [e]);
  }

  // Full-roster display names, so agents who never authored anything (pure
  // voters/citers) can still get a proper hub label instead of a raw id —
  // and so citer names on *other* agents' entries resolve back to an id.
  const displayName = new Map<string, string>();
  for (const a of agents) if (a.name) displayName.set(a.id, a.name);
  for (const e of flat) {
    if (!displayName.has(e.author_id))
      displayName.set(e.author_id, e.author_name);
  }
  const nameToId = new Map<string, string>();
  for (const [id, name] of displayName)
    if (!nameToId.has(name)) nameToId.set(name, id);

  // Agents who only cited/voted on someone else's entry (never authored
  // their own) would otherwise be entirely invisible — surface them as
  // zero-entry hubs so "voted but didn't contribute" is still shown, and
  // so citation edges sourced from them have somewhere to originate.
  const citesGivenByAgent = new Map<string, number>();
  const extraActiveIds = new Set<string>();
  for (const e of flat) {
    for (const citer of e.citers ?? []) {
      const cid = nameToId.get(citer.agentName);
      if (!cid) continue;
      citesGivenByAgent.set(cid, (citesGivenByAgent.get(cid) ?? 0) + 1);
      if (!byAuthor.has(cid)) extraActiveIds.add(cid);
    }
    // Same reasoning for @mentions: an agent can be mentioned before they've
    // authored/cited/voted anything of their own (e.g. invited into a thread
    // mid-discussion) — without a hub for them, buildGraphEdges's mention
    // loop has nowhere to point the line and silently drops it.
    for (const mid of e.mention_agents) {
      if (displayName.has(mid) && !byAuthor.has(mid)) extraActiveIds.add(mid);
    }
  }

  const activeIds = new Set<string>([...byAuthor.keys(), ...extraActiveIds]);
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const a of agents) {
    if (activeIds.has(a.id) && !seen.has(a.id)) {
      ids.push(a.id);
      seen.add(a.id);
    }
  }
  for (const id of activeIds) {
    if (!seen.has(id)) {
      ids.push(id);
      seen.add(id);
    }
  }

  const N = ids.length;
  if (N === 0) {
    return {
      hubs: [],
      nodes: [],
      nodeById: new Map(),
      hubById: new Map(),
      nameToId,
      minX: 0,
      minY: 0,
      maxX: 400,
      maxY: 320,
    };
  }

  const counts = ids.map((id) => (byAuthor.get(id) ?? []).length);
  const maxCount = Math.max(1, ...counts);
  const weights = counts.map((c) => Math.max(c, MIN_WEIGHT));
  const totalWeight = weights.reduce((a, b) => a + b, 0);

  // Ring radius: enough circumference for N evenly-weighted hubs, but also
  // enough raw room for whichever agent contributed the most — otherwise a
  // single prolific agent's own cards cram into each other close to their
  // hub regardless of how wide their wedge is.
  const hubR = Math.max(
    210,
    ((LANE_W + LANE_GUTTER) * N) / (2 * Math.PI),
    maxCount * 27,
  );

  // Sunburst wedge allocation — each agent's angular slice is proportional
  // to their own share of total weighted output, so a heavy contributor
  // gets a proportionally wide slice to spiral their cards into instead of
  // being squeezed into the same fixed wedge as everyone else.
  let cursor = 0;
  const centerAngle: number[] = [];
  const wedgeHalfFor: number[] = [];
  for (let i = 0; i < N; i++) {
    const sliceAngle = (weights[i] / totalWeight) * 2 * Math.PI;
    centerAngle.push(-Math.PI / 2 + cursor + sliceAngle / 2);
    // Cards spiral out inside ±wedgeHalf of their agent's own slice —
    // kept meaningfully narrower than the full slice (and, further down,
    // hard-clamped to it even after collision relaxation nudges things
    // around) so two neighboring agents' clusters can never visually cross
    // into each other's territory.
    wedgeHalfFor.push(Math.min(1.3, sliceAngle * 0.36));
    cursor += sliceAngle;
  }

  const hubs: GraphAgentHub[] = [];
  const nodes: GraphEntryNode[] = [];

  ids.forEach((id, i) => {
    const angle = centerAngle[i];
    const wedgeHalf = wedgeHalfFor[i];
    const hx = hubR * Math.cos(angle);
    const hy = hubR * Math.sin(angle);
    const entries = byAuthor.get(id) ?? [];
    const count = entries.length;
    // Prolific agents get a bit more radial breathing room per card, so
    // their cluster expands outward rather than packing tighter and
    // tighter close to the hub as more cards are added.
    const spacingR = SPACING_R * (1 + Math.min(count, 30) / 30);
    const startR = hubR + START_GAP + Math.min(count, 24) * 2.4;
    let citationTotal = 0;
    let confirmedCount = 0;
    let visibleCount = 0;

    entries.forEach((entry, k) => {
      citationTotal += entry.citation_count;
      const confirmedRound = promotedMap.get(entry.id) ?? null;
      if (confirmedRound !== null) confirmedCount += 1;
      if (entry.is_visible) visibleCount += 1;

      const t = k + 1;
      let pull = 1;
      if (confirmedRound !== null) pull = 0.66;
      else if (!entry.is_visible) pull = 1.24;
      else if (entry.citation_count > 0) {
        pull = 1 - Math.min(entry.citation_count, 5) * 0.035;
      }
      const r = (startR + spacingR * Math.sqrt(t)) * pull;
      const wedgeOffset = wedgeHalf * Math.sin(t * GOLDEN_ANGLE);
      const a = angle + wedgeOffset;
      const cx = r * Math.cos(a);
      const cy = r * Math.sin(a);
      const compact = compactIds.has(entry.id);
      const { w, h } = estimateCardSize(entry, compact);
      nodes.push({
        entry,
        x: cx - w / 2,
        y: cy - h / 2,
        w,
        h,
        confirmedRound,
        compact,
      });
    });

    hubs.push({
      id,
      name: entries[0]?.author_name ?? displayName.get(id) ?? id,
      x: hx,
      y: hy,
      angle,
      entryCount: entries.length,
      visibleCount,
      citationTotal,
      confirmedCount,
      citesGiven: citesGivenByAgent.get(id) ?? 0,
    });
  });

  relaxCollisions(nodes, hubs);

  // ── Angular containment ────────────────────────────────────────────────
  // relaxCollisions above works in raw cartesian space: resolving a local
  // overlap can push a card sideways far enough to visually drift into a
  // neighboring agent's wedge — which reads as "whose card is this?"
  // confusion between agents. Re-clamp every card's angle (around the
  // shared origin) back into its own agent's allocated wedge, preserving
  // whatever radius the collision pass settled on — this guarantees zero
  // cross-agent overlap no matter how far the cartesian push moved a card.
  const wedgeByAuthor = new Map<string, { angle: number; half: number }>();
  ids.forEach((id, i) => {
    wedgeByAuthor.set(id, { angle: centerAngle[i], half: wedgeHalfFor[i] });
  });
  for (const node of nodes) {
    const wedge = wedgeByAuthor.get(node.entry.author_id);
    if (!wedge) continue;
    const cx = node.x + node.w / 2;
    const cy = node.y + node.h / 2;
    const r = Math.hypot(cx, cy) || 0.001;
    const a = Math.atan2(cy, cx);
    const delta = Math.atan2(
      Math.sin(a - wedge.angle),
      Math.cos(a - wedge.angle),
    );
    const limit = wedge.half * 0.94;
    const clampedDelta = Math.min(limit, Math.max(-limit, delta));
    const clamped = wedge.angle + clampedDelta;
    node.x = r * Math.cos(clamped) - node.w / 2;
    node.y = r * Math.sin(clamped) - node.h / 2;
  }
  // The clamp above can occasionally re-touch two cards from the *same*
  // agent that the collision pass had separated mostly angularly — mop
  // those up by pushing them further apart along their own radius only
  // (never sideways), so they still can't escape the wedge just clamped.
  relaxSameAuthorRadially(nodes);

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const expand = (x0: number, y0: number, x1: number, y1: number) => {
    minX = Math.min(minX, x0);
    minY = Math.min(minY, y0);
    maxX = Math.max(maxX, x1);
    maxY = Math.max(maxY, y1);
  };
  for (const h of hubs) {
    expand(
      h.x - HUB_RADIUS,
      h.y - HUB_RADIUS,
      h.x + HUB_RADIUS,
      h.y + HUB_RADIUS,
    );
  }
  for (const nd of nodes) expand(nd.x, nd.y, nd.x + nd.w, nd.y + nd.h);
  if (!isFinite(minX)) {
    minX = -200;
    minY = -160;
    maxX = 200;
    maxY = 160;
  }
  const PAD = 90;
  minX -= PAD;
  minY -= PAD;
  maxX += PAD;
  maxY += PAD;

  // Shift everything so the layout always lives in a (0,0)-origin box —
  // callers can size/scroll the world div directly off maxX/maxY without
  // needing to know about (or re-subtract) an offset.
  for (const h of hubs) {
    h.x -= minX;
    h.y -= minY;
  }
  for (const nd of nodes) {
    nd.x -= minX;
    nd.y -= minY;
  }
  const width = maxX - minX;
  const height = maxY - minY;

  return {
    hubs,
    nodes,
    nodeById: new Map(nodes.map((nd) => [nd.entry.id, nd])),
    hubById: new Map(hubs.map((h) => [h.id, h])),
    nameToId,
    minX: 0,
    minY: 0,
    maxX: width,
    maxY: height,
  };
}

// ─── Edges ───────────────────────────────────────────────────────────────

export type GraphEdgeKind = "reply" | "vote" | "citation" | "mention";

export interface GraphEdge {
  id: string;
  kind: GraphEdgeKind;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  fromKey: string;
  toKey: string;
  /** Whichever agent's color drives this edge — the poster for reply/vote-
   *  as-reply edges, the *mentioned* agent for mention edges (mention edges
   *  are colored via agentColor(mid, ...), not the poster's color), and the
   *  citer/voter for citation/vote-as-citer edges. Toggling that agent off
   *  in the legend's Agents group dims this edge along with their hub and
   *  authored entries. */
  ownerAgentId: string;
}

function nodeCenter(
  layout: GraphLayout,
  id: string,
): { x: number; y: number } | null {
  const node = layout.nodeById.get(id);
  if (node) return { x: node.x + node.w / 2, y: node.y + node.h / 2 };
  const hub = layout.hubById.get(id);
  if (hub) return { x: hub.x, y: hub.y };
  return null;
}

/**
 * Builds every relationship the board tracks as a drawable edge:
 *  - reply / vote → the entry being replied to or voted on
 *  - mention → the mentioned agent's hub
 *  - citation → from the citing agent's hub into the cited entry. Resolved
 *    via `layout.nameToId` (built from the full agent roster), so this
 *    works even for agents who only ever cited/voted and never authored
 *    an entry of their own.
 *
 * Reply/mention edges intentionally color themselves from `agentColor()`
 * *without* passing `promotedAgentIds` — the citation edge (and the
 * "Citation flow" legend entry) already owns gold as *the* one meaning
 * "toward confirmation" on this canvas. If a reply/mention edge also went
 * gold whenever its author happened to be a promoted agent, a solid gold
 * line and a dashed gold line would show up side by side with no way to
 * tell them apart at a glance. Hub avatars/card borders still turn gold
 * for promoted agents elsewhere (that's a node style, not a line, so no
 * ambiguity there).
 */
export function buildGraphEdges(
  layout: GraphLayout,
  agents: { id: string }[],
  promotedAgentIds: Set<string> | undefined,
): GraphEdge[] {
  const edges: GraphEdge[] = [];
  const { nameToId } = layout;

  for (const node of layout.nodes) {
    const entry = node.entry;
    const selfCenter = nodeCenter(layout, entry.id);
    if (!selfCenter) continue;

    if (entry.parentId) {
      const parentCenter = nodeCenter(layout, entry.parentId);
      if (parentCenter) {
        edges.push({
          id: `reply:${entry.id}`,
          kind: entry.entry_type === "vote" ? "vote" : "reply",
          x1: selfCenter.x,
          y1: selfCenter.y,
          x2: parentCenter.x,
          y2: parentCenter.y,
          color: agentColor(entry.author_id, agents),
          ownerAgentId: entry.author_id,
          fromKey: `entry:${entry.id}`,
          toKey: `entry:${entry.parentId}`,
        });
      }
    }

    for (const mid of entry.mention_agents) {
      const hub = layout.hubById.get(mid);
      if (!hub || mid === entry.author_id) continue;
      edges.push({
        id: `mention:${entry.id}:${mid}`,
        kind: "mention",
        x1: selfCenter.x,
        y1: selfCenter.y,
        x2: hub.x,
        y2: hub.y,
        color: agentColor(mid, agents),
        ownerAgentId: mid,
        fromKey: `entry:${entry.id}`,
        toKey: `agent:${mid}`,
      });
    }

    for (const citer of entry.citers ?? []) {
      const citerId = nameToId.get(citer.agentName);
      if (!citerId || citerId === entry.author_id) continue;
      const hub = layout.hubById.get(citerId);
      if (!hub) continue;
      // A real vote never gets its own draft_entries row — the backend
      // records it straight into the votes table, and the frontend learns
      // about it via the same bb-vote → CITE path as an actual citation (see
      // useSwarmRun.ts). The only signal that survives to tell them apart is
      // round: the vote sub-round always tags round=1, and `cite` is never
      // offered to agents before round 2 (_ROUND1_TOOLS has no `cite`;
      // _ROUNDS_TOOLS, used from round 2 on, does) — so round 1 here can
      // only mean a vote, never a real citation.
      const isVote = citer.round === 1;
      edges.push({
        id: `${isVote ? "vote" : "cite"}:${entry.id}:${citerId}:${citer.round}`,
        kind: isVote ? "vote" : "citation",
        x1: hub.x,
        y1: hub.y,
        x2: selfCenter.x,
        y2: selfCenter.y,
        color: agentColor(citerId, agents, promotedAgentIds),
        ownerAgentId: citerId,
        fromKey: `agent:${citerId}`,
        toKey: `entry:${entry.id}`,
      });
    }
  }

  return edges;
}
