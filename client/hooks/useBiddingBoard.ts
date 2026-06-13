"use client";

import { useMemo } from "react";
import { SimStep } from "@/lib/types";

export interface BoardContribution {
  id: string;
  agentId: string;
  agentName: string;
  data: string;
  citation: string;
  source: "bid" | "match";
  coversGapIds: string[];
}

export interface BoardGap {
  id: string;
  postedById: string;
  postedByName: string;
  reason: string;
  expects: string;
  coveredByContributionIds: string[];
  finalUncovered: boolean | null;
}

export interface BiddingBoardState {
  gaps: BoardGap[];
  contributions: BoardContribution[];
  contributionById: Map<string, BoardContribution>;
  unlinkedContributionIds: string[];
  collaboratorIds: Set<string>;
  hasData: boolean;
  finalized: boolean;
}

function parseFencedJson(msg: string): unknown {
  const trimmed = msg.trim();
  const m = trimmed.match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$/i);
  const body = m ? m[1] : trimmed;
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
}

function asString(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asArray<T = unknown>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

function asObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

export function useBiddingBoard(steps: SimStep[]): BiddingBoardState {
  return useMemo(() => parseBoard(steps), [steps]);
}

function parseBoard(steps: SimStep[]): BiddingBoardState {
  const gaps: BoardGap[] = [];
  const gapById = new Map<string, BoardGap>();
  const contributions: BoardContribution[] = [];
  const contributionById = new Map<string, BoardContribution>();
  const collaboratorIds = new Set<string>();
  let finalized = false;

  const addContribution = (c: BoardContribution) => {
    contributions.push(c);
    contributionById.set(c.id, c);
  };

  // Wire a contribution to a gap (both directions), deduped.
  const link = (contribId: string, gapId: string) => {
    const c = contributionById.get(contribId);
    const gap = gapById.get(gapId);
    if (c && !c.coversGapIds.includes(gapId)) c.coversGapIds.push(gapId);
    if (gap && !gap.coveredByContributionIds.includes(contribId)) {
      gap.coveredByContributionIds.push(contribId);
    }
  };

  for (const step of steps) {
    const mt = step.messageType;
    if (!mt) continue;

    if (mt === "bidding_bid") {
      const payload = asObject(parseFencedJson(step.msg));
      if (payload.yielded === true) continue;
      const agentId = step.fromId ?? "";
      const agentName = step.label || agentId;

      asArray(payload.gaps).forEach((raw, idx) => {
        const g = asObject(raw);
        const id = `${agentId}/g${idx}`;
        if (gapById.has(id)) return;
        const entry: BoardGap = {
          id,
          postedById: agentId,
          postedByName: agentName,
          reason: asString(g.reason),
          expects: asString(g.expects),
          coveredByContributionIds: [],
          finalUncovered: null,
        };
        gapById.set(id, entry);
        gaps.push(entry);
      });

      asArray(payload.contribution).forEach((raw, idx) => {
        const c = asObject(raw);
        const data = asString(c.data);
        if (!data) return;
        // Stable id `${agentId}/c${idx}` mirrors the server's F{idx} finding
        // ids, so reuses_finding references resolve directly to this card.
        addContribution({
          id: `${agentId}/c${idx}`,
          agentId,
          agentName,
          data,
          citation: asString(c.citation),
          source: "bid",
          coversGapIds: [],
        });
      });
    } else if (mt === "bidding_match") {
      const payload = asObject(parseFencedJson(step.msg));
      const agentId = step.fromId ?? "";
      const agentName = step.label || agentId;
      asArray<unknown>(payload.gap_coverage).forEach((raw, idx) => {
        const g = asObject(raw);
        if (g.can_contribute !== true) return;
        const gapId = asString(g.gap_id);
        if (!gapId) return;

        // CONNECT: reused bid findings (F{n} → `${agentId}/c{n}`) wire the
        // existing standalone contribution to this gap.
        asArray<unknown>(g.reuses_finding).forEach((rawFid) => {
          const fid = asString(rawFid);
          const m = /^F(\d+)$/.exec(fid);
          if (!m) return;
          link(`${agentId}/c${m[1]}`, gapId);
        });

        // CREATE + CONNECT: genuinely new contributions become match cards.
        asArray<unknown>(g.contribution).forEach((rawC, jdx) => {
          const c = asObject(rawC);
          const data = asString(c.data);
          if (!data) return;
          const cid = `${step.id}/${gapId}/${idx}/${jdx}`;
          addContribution({
            id: cid,
            agentId,
            agentName,
            data,
            citation: asString(c.citation),
            source: "match",
            coversGapIds: [],
          });
          link(cid, gapId);
        });
      });
    } else if (mt === "bidding_collaborators") {
      const payload = asObject(parseFencedJson(step.msg));
      finalized = true;
      asArray<unknown>(payload.collaborators).forEach((raw) => {
        const c = asObject(raw);
        const id = asString(c.id);
        if (id) collaboratorIds.add(id);
      });
      const uncoveredIds = new Set(
        asArray<unknown>(payload.uncovered_gaps)
          .map((raw) => asString(asObject(raw).gap_id))
          .filter(Boolean),
      );
      gaps.forEach((g) => {
        g.finalUncovered = uncoveredIds.has(g.id);
      });
    }
  }

  const unlinkedContributionIds = contributions
    .filter((c) => c.source === "bid" && c.coversGapIds.length === 0)
    .map((c) => c.id);

  return {
    gaps,
    contributions,
    contributionById,
    unlinkedContributionIds,
    collaboratorIds,
    hasData: gaps.length > 0 || contributions.length > 0,
    finalized,
  };
}
