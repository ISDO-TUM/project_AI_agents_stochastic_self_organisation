"use client";

import { motion } from "framer-motion";
import { Pin, CheckCircle2, FileText } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT, BURG_DIM } from "@/lib/theme";
import { ConfirmedEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";

interface ConfirmedCardProps {
  entry: ConfirmedEntry;
}

function entryStyle(type: ConfirmedEntry["entry_type"]) {
  if (type === "anchor")
    return {
      icon: <Pin size={11} strokeWidth={2} color={BURG_LT} />,
      label: "ANCHOR",
      color: BURG_LT,
      bg: BURG_DIM,
      border: "rgba(139,26,47,0.3)",
    };
  if (type === "finding")
    return {
      icon: <CheckCircle2 size={11} strokeWidth={2} color="#3dba8c" />,
      label: "FINDING",
      color: "#3dba8c",
      bg: "rgba(61,186,140,0.08)",
      border: "rgba(61,186,140,0.25)",
    };
  return {
    icon: <FileText size={11} strokeWidth={2} color="#7b9ec0" />,
    label: "SYSTEM",
    color: "#7b9ec0",
    bg: "rgba(123,158,192,0.08)",
    border: "rgba(123,158,192,0.25)",
  };
}

export function ConfirmedCard({ entry }: ConfirmedCardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const s = entryStyle(entry.entry_type);

  return (
    <motion.div
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      style={{
        background: s.bg,
        border: `1px solid ${s.border}`,
        borderRadius: 9,
        padding: "10px 14px",
        marginBottom: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 6,
        }}
      >
        {s.icon}
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            color: s.color,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui",
          }}
        >
          {s.label}
        </span>
        {entry.entry_type !== "anchor" && (
          <span style={{ fontSize: 10, color: t.textDim }}>
            Round {entry.round_confirmed}
          </span>
        )}
        {entry.citation_count > 0 && (
          <span style={{ marginLeft: "auto", fontSize: 10, color: t.textDim }}>
            ♡ {entry.citation_count}
          </span>
        )}
      </div>
      <div style={{ fontSize: 13, color: t.text, lineHeight: 1.6 }}>
        <MarkdownRenderer content={entry.content} />
      </div>
    </motion.div>
  );
}
