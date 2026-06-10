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

  const link = (contribId: string, gapId: string) => {
    const c = contributionById.get(contribId);
    const gap = gapById.get(gapId);
    const canonicalId = gap ? gap.id : gapId;
    if (c && !c.coversGapIds.includes(canonicalId)) {
      c.coversGapIds.push(canonicalId);
    }
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
        const existing = gapById.get(id);
        if (existing) {
          // Re-bid from the same agent: refresh content, keep the stable card.
          existing.reason = asString(g.reason);
          existing.expects = asString(g.expects);
          return;
        }
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
        const id = `${agentId}/c${idx}`;
        const existing = contributionById.get(id);
        if (existing) {
          // Re-bid from the same agent: refresh content, keep the stable card.
          existing.data = data;
          existing.citation = asString(c.citation);
          return;
        }
        addContribution({
          id,
          agentId,
          agentName,
          data,
          citation: asString(c.citation),
          source: "bid",
          coversGapIds: [],
        });
      });
    } else if (mt === "system_blackboard") {
      // The gap board carries the server's canonical gap ids (`g0`,
      // `r0g0`, …) alongside the verbatim reason/expects text. Alias those
      // ids onto the gaps parsed from bids so that bidding_match and
      // bidding_collaborators references — which use the server ids —
      // resolve regardless of the server's id scheme.
      const entryRe =
        /^- gap_id: (.+)\n\s+posted_by: (.+)\n\s+reason: ([\s\S]*?)\n\s+expects: ([\s\S]*?)(?=\n- gap_id: |$)/gm;
      for (const m of step.msg.matchAll(entryRe)) {
        const [, rawId, postedByName, rawReason, rawExpects] = m;
        const id = rawId.trim();
        if (gapById.has(id)) continue;
        const postedById = id.split("/")[0];
        const reason = rawReason.trim();
        const existing = gaps.find(
          (g) => g.postedById === postedById && g.reason.trim() === reason,
        );
        if (existing) {
          gapById.set(id, existing);
          continue;
        }
        const entry: BoardGap = {
          id,
          postedById,
          postedByName: postedByName.trim(),
          reason,
          expects: rawExpects.trim(),
          coveredByContributionIds: [],
          finalUncovered: null,
        };
        gapById.set(id, entry);
        gaps.push(entry);
      }
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
          if (contributionById.has(cid)) {
            link(cid, gapId);
            return;
          }
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
      // Resolve uncovered gap ids through gapById — the server's ids may be
      // aliases of client-side gaps rather than their primary id.
      const uncoveredGaps = new Set<BoardGap>();
      asArray<unknown>(payload.uncovered_gaps).forEach((raw) => {
        const g = gapById.get(asString(asObject(raw).gap_id));
        if (g) uncoveredGaps.add(g);
      });
      gaps.forEach((g) => {
        g.finalUncovered = uncoveredGaps.has(g);
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
