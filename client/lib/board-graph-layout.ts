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


function estimateCardSize(entry: FlatEntry): { w: number; h: number } {
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
    if (!displayName.has(e.author_id)) displayName.set(e.author_id, e.author_name);
  }
  const nameToId = new Map<string, string>();
  for (const [id, name] of displayName) if (!nameToId.has(name)) nameToId.set(name, id);

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
    wedgeHalfFor.push(Math.min(1.48, sliceAngle * 0.42));
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
      const { w, h } = estimateCardSize(entry);
      nodes.push({
        entry,
        x: cx - w / 2,
        y: cy - h / 2,
        w,
        h,
        confirmedRound,
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
    expand(h.x - HUB_RADIUS, h.y - HUB_RADIUS, h.x + HUB_RADIUS, h.y + HUB_RADIUS);
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
          color: agentColor(entry.author_id, agents, promotedAgentIds),
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
        color: agentColor(mid, agents, promotedAgentIds),
        fromKey: `entry:${entry.id}`,
        toKey: `agent:${mid}`,
      });
    }

    for (const citer of entry.citers ?? []) {
      const citerId = nameToId.get(citer.agentName);
      if (!citerId || citerId === entry.author_id) continue;
      const hub = layout.hubById.get(citerId);
      if (!hub) continue;
      edges.push({
        id: `cite:${entry.id}:${citerId}:${citer.round}`,
        kind: "citation",
        x1: hub.x,
        y1: hub.y,
        x2: selfCenter.x,
        y2: selfCenter.y,
        color: agentColor(citerId, agents, promotedAgentIds),
        fromKey: `agent:${citerId}`,
        toKey: `entry:${entry.id}`,
      });
    }
  }

  return edges;
}
