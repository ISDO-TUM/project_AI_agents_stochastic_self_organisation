"use client";

import { DraftEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface DraftEntryProps {
  entry: DraftEntry;
  depth?: number;
}

const MAX_DEPTH = 4;
const INDENT_PX = 16;

const ENTRY_TYPE_BADGE: Record<DraftEntry["entry_type"], string> = {
  proposal: "P",
  reply: "R",
  vote: "V",
  system: "⚙",
};

export function DraftEntryComponent({ entry, depth = 0 }: DraftEntryProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const indent = Math.min(depth, MAX_DEPTH) * INDENT_PX;
  const opacity = entry.is_visible ? 1 : 0.3;

  return (
    <div style={{ marginLeft: indent, opacity }}>
      <div
        style={{
          padding: "10px 12px",
          marginBottom: 4,
          borderRadius: 6,
          background: dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)",
          borderLeft:
            depth > 0
              ? `2px solid ${(t as { border?: string }).border ?? "rgba(139,26,47,0.3)"}`
              : "none",
        }}
      >
        {/* Header row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 6,
            fontSize: 11,
            color: dark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.45)",
          }}
        >
          <span
            style={{
              background: "rgba(139,26,47,0.15)",
              color: "#8B1A2F",
              borderRadius: 3,
              padding: "1px 5px",
              fontWeight: 700,
              fontSize: 10,
            }}
          >
            {ENTRY_TYPE_BADGE[entry.entry_type]}
          </span>
          <span style={{ fontWeight: 600 }}>{entry.author_name}</span>
          <span>R{entry.round}</span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <span title="Citations">♡ {entry.citation_count}</span>
            {entry.children.length > 0 && (
              <span title="Replies">💬 {entry.children.length}</span>
            )}
          </span>
        </div>

        {/* Content */}
        <div style={{ fontSize: 13 }}>
          <MarkdownRenderer content={entry.content} />
        </div>

        {/* Entry ID (small, for debugging) */}
        <div
          style={{
            fontSize: 9,
            color: dark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)",
            marginTop: 4,
            fontFamily: "monospace",
          }}
        >
          {entry.id.slice(0, 8)}
        </div>
      </div>

      {/* Recursive children */}
      {entry.children.map((child) => (
        <DraftEntryComponent key={child.id} entry={child} depth={depth + 1} />
      ))}
    </div>
  );
}
