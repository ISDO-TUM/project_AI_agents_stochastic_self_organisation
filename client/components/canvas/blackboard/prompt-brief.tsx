"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, ChevronRight, Copy, ScrollText } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { BURG_LT } from "@/lib/theme";
import { MarkdownRenderer } from "@/components/markdown-renderer";

interface PromptBriefProps {
  /** The active thread's description — the market maker's brief for it. */
  text: string;
}

// Roughly two lines of body copy at this card's font size/width before the
// clamp kicks in and an expand toggle becomes worth showing.
const CLAMP_THRESHOLD = 160;

/** The market maker's brief for the active thread, shown first in the Draft
 *  board. Mirrors final-answer-reveal.tsx's copy/expand interaction. */
export function PromptBrief({ text }: PromptBriefProps) {
  const { dark } = useTheme();
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const needsClamp = text.trim().length > CLAMP_THRESHOLD;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (!text.trim()) return null;

  return (
    <div
      style={{
        padding: "10px 13px",
        borderRadius: 10,
        background: dark ? "rgba(139,26,47,0.10)" : "rgba(139,26,47,0.05)",
        border: "1px solid rgba(139,26,47,0.28)",
        marginBottom: 12,
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
        <ScrollText size={12} strokeWidth={2} color={BURG_LT} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            color: BURG_LT,
            letterSpacing: "0.09em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          Brief
        </span>
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <button
            onClick={handleCopy}
            title={copied ? "Copied!" : "Copy brief"}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 5px",
              borderRadius: 6,
              color: copied ? "#3dba8c" : BURG_LT,
              fontSize: 10,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              fontWeight: 600,
            }}
          >
            {copied ? (
              <Check size={11} strokeWidth={2.5} />
            ) : (
              <Copy size={11} strokeWidth={1.8} />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
          {needsClamp && (
            <button
              onClick={() => setExpanded((v) => !v)}
              title={expanded ? "Collapse" : "Expand"}
              style={{
                display: "flex",
                alignItems: "center",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "2px 4px",
                opacity: 0.7,
                color: BURG_LT,
              }}
            >
              <motion.span
                animate={{ rotate: expanded ? 90 : 0 }}
                transition={{ duration: 0.18 }}
                style={{ display: "flex" }}
              >
                <ChevronRight size={12} strokeWidth={2.5} />
              </motion.span>
            </button>
          )}
        </div>
      </div>
      <div
        style={{
          fontSize: 12.5,
          lineHeight: 1.55,
          color: dark ? "rgba(255,240,242,0.9)" : "rgba(30,10,15,0.88)",
          display: !expanded && needsClamp ? "-webkit-box" : "block",
          WebkitLineClamp: !expanded && needsClamp ? 2 : "unset",
          WebkitBoxOrient: "vertical",
          overflow: !expanded && needsClamp ? "hidden" : "visible",
        }}
      >
        <MarkdownRenderer content={text} />
      </div>
      <AnimatePresence initial={false}>
        {needsClamp && (
          <motion.div
            initial={false}
            animate={{ opacity: 1 }}
            style={{ marginTop: 2 }}
          >
            <button
              onClick={() => setExpanded((v) => !v)}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: 0,
                fontSize: 10.5,
                fontWeight: 600,
                color: BURG_LT,
                opacity: 0.75,
              }}
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
