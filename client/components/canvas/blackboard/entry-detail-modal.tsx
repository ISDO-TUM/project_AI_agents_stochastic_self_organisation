"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { AtSign, CheckCircle2, EyeOff, X } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { GraphEntryNode } from "@/lib/board-graph-layout";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { CitationRing } from "./citation-ring";

const GOLD = "#b5860d";

interface EntryDetailModalProps {
  node: GraphEntryNode;
  color: string;
  threshold: number;
  onClose: () => void;
}

/** Centered full-content view of one graph entry over a blurred backdrop.
 *  Mirrors final-answer-reveal.tsx's portal/dismissal pattern; replaces the
 *  old anchored expand-popover on graph cards. */
export function EntryDetailModal({
  node,
  color,
  threshold,
  onClose,
}: EntryDetailModalProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const { entry } = node;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="entry-detail-modal"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.18 }}
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 10000,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          background: dark ? "rgba(0,0,0,0.55)" : "rgba(245,242,232,0.5)",
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 14, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 10, scale: 0.98 }}
          transition={{ type: "spring", stiffness: 300, damping: 26 }}
          style={{
            width: "min(560px, 92vw)",
            maxHeight: "80vh",
            display: "flex",
            flexDirection: "column",
            background: dark ? "rgba(12,10,4,0.97)" : "rgba(255,253,245,0.99)",
            border: `1px solid ${
              node.confirmedRound !== null
                ? "rgba(181,134,13,0.4)"
                : `${color}55`
            }`,
            borderRadius: 16,
            overflow: "hidden",
            boxShadow: "0 30px 90px rgba(0,0,0,0.5)",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "12px 16px",
              borderBottom: `1px solid ${
                dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.07)"
              }`,
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: 22,
                height: 22,
                borderRadius: "50%",
                background: `${color}26`,
                color,
                border: `1px solid ${color}55`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 800,
                flexShrink: 0,
              }}
            >
              {(entry.author_name || "?")[0]?.toUpperCase() ?? "?"}
            </span>
            <span style={{ fontSize: 13.5, fontWeight: 700, color: t.text }}>
              {entry.author_name}
            </span>
            <span
              style={{
                fontSize: 9,
                fontWeight: 800,
                color,
                background: `${color}1f`,
                borderRadius: 4,
                padding: "1.5px 6px",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
              }}
            >
              {entry.entry_type}
            </span>
            <span
              style={{
                fontSize: 10,
                color: t.textDim,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              R{entry.round}
            </span>
            {node.confirmedRound !== null && (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 3,
                  fontSize: 9.5,
                  fontWeight: 700,
                  color: GOLD,
                }}
              >
                <CheckCircle2 size={11} strokeWidth={2} />
                Confirmed R{node.confirmedRound}
              </span>
            )}
            <button
              onClick={onClose}
              title="Close (Esc)"
              style={{
                marginLeft: "auto",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 6px",
                display: "flex",
                alignItems: "center",
                color: t.textDim,
                borderRadius: 6,
              }}
            >
              <X size={15} strokeWidth={2} />
            </button>
          </div>

          {/* Body */}
          <div
            style={{ overflowY: "auto", padding: "14px 18px 16px" }}
            className="pscroll"
          >
            {!entry.is_visible && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 11,
                  color: t.textDim,
                  fontStyle: "italic",
                  marginBottom: 8,
                }}
              >
                <EyeOff size={11} strokeWidth={2} />
                evaporated at round {entry.round}
              </div>
            )}
            <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
              <MarkdownRenderer content={entry.content} fontSize={13} compact />
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <CitationRing
                count={entry.citation_count}
                threshold={threshold}
                variant="compact"
                citers={entry.citers}
                promotedRound={node.confirmedRound ?? undefined}
              />
              {entry.mention_agents.length > 0 && (
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 3,
                    fontSize: 10,
                    color: t.textDim,
                  }}
                >
                  <AtSign size={10} strokeWidth={2} />
                  {entry.mention_agents.length} mentioned
                </span>
              )}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
}
