import { ConfirmedEntry, DraftEntry } from "./types";

export function truncate(text: string, max = 60): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}…` : clean;
}

function collectAuthors(entries: DraftEntry[], authors: Set<string>): void {
  for (const e of entries) {
    authors.add(e.author_id);
    collectAuthors(e.children, authors);
  }
}

/** Mirrors the backend `promotion_threshold` helper: about a third of the
 *  participants, at least one, capped at n-1 so it never exceeds the number of
 *  agents able to endorse an entry (an author can't endorse their own post).
 *  Only a fallback — the server sends the authoritative per-thread value on the
 *  "Thread assignment" step (ThreadInfo.promotion_threshold); this estimate is
 *  used only for the combined all-threads view, where there is no single true M. */
export function computePromotionThreshold(draft: DraftEntry[]): number {
  const authors = new Set<string>();
  collectAuthors(draft, authors);
  const n = authors.size;
  return Math.max(1, Math.min(n - 1, Math.floor(n / 3) + 1));
}

/** Total entry count including nested replies — ``draft.length`` alone only
 *  counts top-level proposals, since replies are nested under their parent's
 *  ``children`` rather than appended to the top-level array. */
export function countEntries(entries: DraftEntry[]): number {
  let count = 0;
  for (const e of entries) {
    count += 1 + countEntries(e.children);
  }
  return count;
}

export function findDraftEntry(
  entries: DraftEntry[],
  targetId: string,
): DraftEntry | null {
  for (const e of entries) {
    if (e.id === targetId) return e;
    const found = findDraftEntry(e.children, targetId);
    if (found) return found;
  }
  return null;
}

/** Resolves the truncated content of the entry a reply/vote points at via reply_to. */
export function resolveParentPreview(
  draft: DraftEntry[],
  replyTo: string | null,
): string {
  if (!replyTo) return "";
  const parent = findDraftEntry(draft, replyTo);
  return parent ? truncate(parent.content) : "";
}

/** Sums citation_count over every entry authored by each agent, recursively. */
export function computeCitationsByAuthor(
  draft: DraftEntry[],
): Map<string, number> {
  const map = new Map<string, number>();
  function walk(entries: DraftEntry[]): void {
    for (const e of entries) {
      map.set(e.author_id, (map.get(e.author_id) ?? 0) + e.citation_count);
      walk(e.children);
    }
  }
  walk(draft);
  return map;
}

/** Author IDs whose draft entry has been promoted (i.e. some confirmed_entries
 *  row's source_draft_id resolves back to a draft entry by this author). */
export function computePromotedAuthorIds(
  draft: DraftEntry[],
  confirmed: ConfirmedEntry[],
): Set<string> {
  const ids = new Set<string>();
  for (const c of confirmed) {
    if (!c.source_draft_id) continue;
    const sourceEntry = findDraftEntry(draft, c.source_draft_id);
    if (sourceEntry) ids.add(sourceEntry.author_id);
  }
  return ids;
}
