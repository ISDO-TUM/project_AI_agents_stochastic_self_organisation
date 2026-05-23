"use client";

import { DraftEntry } from "@/lib/types";
import { DraftEntryComponent } from "@/components/draft-entry";
import { useTheme } from "@/lib/theme-context";

interface DraftSectionProps {
  entries: DraftEntry[];
}

export function DraftSection({ entries }: DraftSectionProps) {
  const { dark } = useTheme();

  if (entries.length === 0) {
    return (
      <div
        style={{
          fontSize: 13,
          color: dark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.3)",
          padding: "16px 0",
          textAlign: "center",
        }}
      >
        No draft entries yet.
      </div>
    );
  }

  return (
    <div>
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
        Draft
      </div>
      {entries.map((entry) => (
        <DraftEntryComponent key={entry.id} entry={entry} depth={0} />
      ))}
    </div>
  );
}
