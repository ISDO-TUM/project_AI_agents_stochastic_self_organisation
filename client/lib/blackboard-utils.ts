import { DraftEntry } from "./types";

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

/** Mirrors the backend formula in PRD §15: M = max(1, N_participants // 3 + 1). */
export function computePromotionThreshold(draft: DraftEntry[]): number {
  const authors = new Set<string>();
  collectAuthors(draft, authors);
  return Math.max(1, Math.floor(authors.size / 3) + 1);
}

function findById(entries: DraftEntry[], targetId: string): DraftEntry | null {
  for (const e of entries) {
    if (e.id === targetId) return e;
    const found = findById(e.children, targetId);
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
  const parent = findById(draft, replyTo);
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
