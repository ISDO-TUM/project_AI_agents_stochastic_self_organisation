"use client";

import { ConfirmedEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface ConfirmedSectionProps {
  entries: ConfirmedEntry[];
}

const ENTRY_BADGE: Record<ConfirmedEntry["entry_type"], string> = {
  anchor: "📌",
  finding: "✅",
  system: "⚙",
};

export function ConfirmedSection({ entries }: ConfirmedSectionProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  if (entries.length === 0) return null;

  return (
    <div
      style={{
        borderBottom: `1px solid ${(t as { border?: string }).border ?? "rgba(139,26,47,0.2)"}`,
        paddingBottom: 12,
        marginBottom: 12,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        Confirmed
      </div>

      {entries.map((entry) => (
        <div
          key={entry.id}
          style={{
            padding: "8px 10px",
            marginBottom: 4,
            borderRadius: 6,
            background: dark ? "rgba(255,215,0,0.06)" : "rgba(255,215,0,0.08)",
            borderLeft: "3px solid rgba(255,215,0,0.5)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 4,
              fontSize: 11,
              color: dark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.45)",
            }}
          >
            <span>{ENTRY_BADGE[entry.entry_type]}</span>
            <span style={{ fontWeight: 600 }}>
              {entry.entry_type === "anchor" ? "ANCHOR" : `R${entry.round_confirmed}`}
            </span>
            {entry.citation_count > 0 && <span>♡ {entry.citation_count}</span>}
          </div>
          <div style={{ fontSize: 13 }}>
            <MarkdownRenderer content={entry.content} />
          </div>
        </div>
      ))}
    </div>
  );
}
