"use client";

import { Check } from "lucide-react";
import { DraftEntry, ThreadInfo } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT } from "@/lib/theme";
import { ProposalCard } from "./proposal-card";
import { ThreadedEntry } from "./reply-thread";

interface DraftEntryStreamProps {
  /** Already-filtered entries to render, in stream order. */
  entries: DraftEntry[];
  /** All threads (sub-tasks) of the contract, in contract order. */
  threads: ThreadInfo[];
  /** Active thread filter — when set (or single-thread), the stream renders a
   *  flat round timeline; only the unfiltered multi-thread view groups by task. */
  activeThreadId?: string | null;
  threshold: number;
  promotedMap: Map<string, number>;
  agents?: { id: string }[];
  promotedAgentIds?: Set<string>;
  /** Threads that have reached at least one confirmed entry — marks a task as
   *  converged in its header. */
  confirmedThreadIds?: Set<string>;
  /** Clicking a sub-task header filters the board to that task. */
  onSelectThread?: (id: string | null) => void;
}

function groupByRound(
  entries: DraftEntry[],
): { round: number; entries: DraftEntry[] }[] {
  return entries.reduce<{ round: number; entries: DraftEntry[] }[]>(
    (acc, entry) => {
      const last = acc[acc.length - 1];
      if (last && last.round === entry.round) last.entries.push(entry);
      else acc.push({ round: entry.round, entries: [entry] });
      return acc;
    },
    [],
  );
}

/**
 * Renders the draft board's entries. In an unfiltered multi-thread run it groups
 * proposals under a sub-task header numbered to match the contract's Schedule of
 * Work, so every proposal is visibly tied to the task it addresses. Otherwise it
 * falls back to a flat round-by-round timeline (single thread, or one task
 * filtered in). Shared by the inline board and its fullscreen modal.
 */
export function DraftEntryStream({
  entries,
  threads,
  activeThreadId,
  threshold,
  promotedMap,
  agents = [],
  promotedAgentIds,
  confirmedThreadIds,
  onSelectThread,
}: DraftEntryStreamProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const renderEntry = (entry: DraftEntry) =>
    entry.entry_type === "proposal" ? (
      <ProposalCard
        key={entry.id}
        entry={entry}
        threshold={threshold}
        promotedMap={promotedMap}
        agents={agents}
        promotedAgentIds={promotedAgentIds}
      />
    ) : (
      <ThreadedEntry
        key={entry.id}
        entry={entry}
        parentContent=""
        depth={0}
        threshold={threshold}
        promotedMap={promotedMap}
        agents={agents}
        promotedAgentIds={promotedAgentIds}
      />
    );

  const roundDivider = (round: number) => (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        margin: "10px 0 8px",
      }}
    >
      <div
        style={{
          flex: 1,
          height: 1,
          background: dark ? "rgba(139,26,47,0.18)" : "rgba(139,26,47,0.1)",
        }}
      />
      <span
        style={{
          fontSize: 9.5,
          color: dark ? "rgba(196,55,79,0.5)" : "rgba(139,26,47,0.4)",
          fontFamily: "'JetBrains Mono', monospace",
          whiteSpace: "nowrap",
        }}
      >
        Round {round}
      </span>
      <div
        style={{
          flex: 1,
          height: 1,
          background: dark ? "rgba(139,26,47,0.18)" : "rgba(139,26,47,0.1)",
        }}
      />
    </div>
  );

  // Flat round timeline, used by both branches for the entries themselves.
  const renderRoundTimeline = (list: DraftEntry[], keyPrefix: string) =>
    groupByRound(list).map((group, gi) => (
      <div key={`${keyPrefix}-r${group.round}-${gi}`}>
        {gi > 0 && roundDivider(group.round)}
        {group.entries.map(renderEntry)}
      </div>
    ));

  const groupByTask = !activeThreadId && threads.length > 1;

  if (!groupByTask) {
    return <>{renderRoundTimeline(entries, "flat")}</>;
  }

  // ── Task-grouped view: one section per sub-task, in contract order ──
  const seen = new Set<string>();
  const sections = threads.map((th, i) => {
    const own = entries.filter((e) => e.thread_id === th.id);
    own.forEach((e) => seen.add(e.id));
    return { thread: th, index: i, entries: own };
  });
  // Defensive: any entry whose thread isn't in the contract still shows, trailing.
  const orphans = entries.filter((e) => !seen.has(e.id));

  return (
    <>
      {sections.map(({ thread, index, entries: own }) => {
        const converged = confirmedThreadIds?.has(thread.id) ?? false;
        return (
          <div key={thread.id} style={{ marginBottom: 6 }}>
            <button
              onClick={
                onSelectThread ? () => onSelectThread(thread.id) : undefined
              }
              title={onSelectThread ? `Focus “${thread.title}”` : thread.title}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                gap: 9,
                padding: "7px 11px",
                marginBottom: 10,
                borderRadius: 8,
                textAlign: "left",
                background: dark
                  ? "rgba(139,26,47,0.14)"
                  : "rgba(139,26,47,0.07)",
                border: "1px solid rgba(139,26,47,0.24)",
                borderLeft: `3px solid ${BURG_LT}`,
                cursor: onSelectThread ? "pointer" : "default",
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: BURG_LT,
                  flexShrink: 0,
                }}
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              <span
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontSize: 12,
                  fontWeight: 700,
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  color: t.text,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {thread.title}
              </span>
              {converged && (
                <Check size={12} strokeWidth={2.5} color="#3dba8c" />
              )}
              <span
                style={{
                  fontSize: 9.5,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: t.textDim,
                  flexShrink: 0,
                }}
              >
                {own.length}
              </span>
            </button>

            {own.length > 0 ? (
              renderRoundTimeline(own, thread.id)
            ) : (
              <div
                style={{
                  fontSize: 11,
                  fontStyle: "italic",
                  color: t.textDim,
                  padding: "2px 0 10px 11px",
                }}
              >
                Awaiting proposals…
              </div>
            )}
          </div>
        );
      })}
      {orphans.length > 0 && renderRoundTimeline(orphans, "orphans")}
    </>
  );
}
