import { BlackboardState, DraftEntry } from "./types";

/**
 * Pull a result table out of the swarm's blackboard so it can be shown beneath
 * the synthesised final answer.
 *
 * The answer itself is short prose; when a run's deliverable is a table (e.g.
 * the order-allocation demo's `FINAL ALLOCATION TABLE:` block written by the
 * fulfillment manager), that table lives in the author's blackboard message,
 * not in the synthesis. The manager usually posts last and its message is not
 * cited afterwards, so the table is normally a *draft* entry rather than a
 * confirmed finding — we search both, drafts first.
 *
 * Returns a GitHub-flavoured Markdown table string (ready for MarkdownRenderer)
 * or null when no table is present. Both a Markdown table and a raw CSV block
 * following a `… TABLE:` marker are recognised; CSV is converted to Markdown.
 */
export function extractResultTable(bb: BlackboardState): string | null {
  for (const content of collectContents(bb)) {
    const table = extractTableFromText(content);
    if (table) return table;
  }
  return null;
}

/** Draft messages (tree-flattened, newest-first) then confirmed findings. */
function collectContents(bb: BlackboardState): string[] {
  const out: string[] = [];
  const walk = (entries: DraftEntry[]) => {
    for (const e of entries) {
      if (e.content) out.push(e.content);
      if (e.children?.length) walk(e.children);
    }
  };
  walk(bb.draft);
  for (const c of bb.confirmed) if (c.content) out.push(c.content);
  return out;
}

function extractTableFromText(text: string): string | null {
  return extractMarkdownTable(text) ?? extractCsvTable(text);
}

/** A contiguous run of pipe rows anchored by a `| --- | --- |` separator. */
function extractMarkdownTable(text: string): string | null {
  const lines = text.split("\n");
  let start = -1;
  for (let i = 0; i < lines.length - 1; i++) {
    const sep = lines[i + 1].trim();
    if (
      lines[i].includes("|") &&
      sep.includes("-") &&
      /^\|?[\s:|-]+\|?$/.test(sep)
    ) {
      start = i;
      break;
    }
  }
  if (start < 0) return null;
  const block: string[] = [];
  for (let i = start; i < lines.length; i++) {
    if (lines[i].includes("|")) block.push(lines[i].trim());
    else break;
  }
  return block.length >= 3 ? block.join("\n") : null;
}

/** CSV rows following a line that ends in `TABLE:` — converted to Markdown. */
function extractCsvTable(text: string): string | null {
  const marker = text.match(/[^\n]*TABLE:?[ \t]*\n/i);
  if (!marker || marker.index == null) return null;
  const after = text.slice(marker.index + marker[0].length);

  const rows: string[][] = [];
  for (const raw of after.split("\n")) {
    const line = raw.replace(/^```(?:csv)?/i, "").replace(/```$/, "").trim();
    if (!line) {
      if (rows.length) break; // blank line ends the block once we have rows
      continue;
    }
    // Stop at the write-confirmation line, rationale bullets, or any non-CSV prose.
    if (/^write confirmation/i.test(line) || /^[-*•]/.test(line)) break;
    if (!line.includes(",")) break;
    rows.push(line.split(",").map((c) => c.trim()));
  }
  if (rows.length < 2) return null;

  const header = rows[0];
  const body = rows.slice(1).filter((r) => r.length === header.length);
  if (body.length === 0) return null;
  return [
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...body.map((r) => `| ${r.join(" | ")} |`),
  ].join("\n");
}
