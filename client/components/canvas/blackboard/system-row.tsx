"use client";

import { useState } from "react";
import { Settings2, ChevronDown } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { DraftEntry } from "@/lib/types";

interface SystemRowProps {
  entry: DraftEntry;
}

export function SystemRow({ entry }: SystemRowProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [open, setOpen] = useState(false);

  return (
    <div
      style={{
        marginBottom: 5,
        borderRadius: 6,
        background: dark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
        opacity: 0.75,
      }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          width: "100%",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "5px 9px",
          fontSize: 10.5,
          color: t.textDim,
          textAlign: "left",
        }}
      >
        <Settings2 size={10} strokeWidth={2} />
        <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          R{entry.round}
        </span>
        <span
          style={{
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: open ? "normal" : "nowrap",
          }}
        >
          {entry.content}
        </span>
        <ChevronDown
          size={10}
          style={{
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform 0.15s",
          }}
        />
      </button>
    </div>
  );
}
