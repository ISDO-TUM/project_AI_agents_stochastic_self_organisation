"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Pin, CheckCircle2, FileText, Copy, Check, Heart } from "lucide-react";
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
      accentColor: BURG_LT,
      bg: BURG_DIM,
      border: "rgba(139,26,47,0.2)",
    };
  if (type === "finding")
    return {
      icon: <CheckCircle2 size={11} strokeWidth={2} color="#3dba8c" />,
      label: "FINDING",
      color: "#3dba8c",
      accentColor: "#3dba8c",
      bg: "rgba(61,186,140,0.06)",
      border: "rgba(61,186,140,0.18)",
    };
  return {
    icon: <FileText size={11} strokeWidth={2} color="#7b9ec0" />,
    label: "SYSTEM",
    color: "#7b9ec0",
    accentColor: "#7b9ec0",
    bg: "rgba(123,158,192,0.06)",
    border: "rgba(123,158,192,0.18)",
  };
}

export function ConfirmedCard({ entry }: ConfirmedCardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const s = entryStyle(entry.entry_type);
  const [hovered, setHovered] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(entry.content).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: "relative",
        background: s.bg,
        border: `1px solid ${s.border}`,
        borderLeft: `4px solid ${s.accentColor}`,
        borderRadius: 9,
        padding: "10px 14px",
        marginBottom: 8,
      }}
    >
      {/* ── Header ── */}
      <div
        style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}
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
            R{entry.round_confirmed}
          </span>
        )}
        <div
          style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}
        >
          {entry.citation_count > 0 && (
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: 3,
                fontSize: 10,
                color: t.textDim,
              }}
            >
              <Heart size={9} strokeWidth={2} />
              {entry.citation_count}
            </span>
          )}
          {/* Copy button — fades in on hover */}
          <button
            onClick={handleCopy}
            title={copied ? "Copied!" : "Copy to clipboard"}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 4px",
              display: "flex",
              alignItems: "center",
              color: copied ? s.color : t.textDim,
              opacity: hovered || copied ? 1 : 0,
              transition: "opacity 0.15s, color 0.15s",
              borderRadius: 4,
            }}
          >
            {copied
              ? <Check size={11} strokeWidth={2.5} />
              : <Copy size={11} strokeWidth={1.8} />}
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div style={{ fontSize: 13, color: t.text, lineHeight: 1.6 }}>
        <MarkdownRenderer content={entry.content} />
      </div>
    </motion.div>
  );
}
