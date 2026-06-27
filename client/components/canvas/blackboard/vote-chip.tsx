"use client";

import { CheckCircle } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { DraftEntry } from "@/lib/types";

interface VoteChipProps {
  entry: DraftEntry;
  votedEntryPreview: string;
}

export function VoteChip({ entry, votedEntryPreview }: VoteChipProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: "6px 10px",
        marginBottom: 6,
        borderRadius: 7,
        background: dark ? "rgba(61,186,140,0.06)" : "rgba(61,186,140,0.05)",
        border: "1px solid rgba(61,186,140,0.2)",
        fontSize: 11.5,
        opacity: entry.is_visible ? 1 : 0.35,
      }}
    >
      <CheckCircle size={12} strokeWidth={2} color="#3dba8c" />
      <span style={{ fontWeight: 700, color: t.text }}>
        {entry.author_name}
      </span>
      <span style={{ color: t.textDim }}>voted</span>
      <span
        style={{
          color: t.textDim,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
        }}
      >
        R{entry.round}
      </span>
      {votedEntryPreview && (
        <span
          style={{
            color: t.textSub,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          &quot;{votedEntryPreview}&quot;
        </span>
      )}
    </div>
  );
}
