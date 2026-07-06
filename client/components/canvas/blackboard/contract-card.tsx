"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, ScrollText } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT } from "@/lib/theme";
import { ContractInfo, ThreadInfo } from "@/lib/types";
import { ContractDocument, humanizeTaskType } from "./contract-document";

interface ContractCardProps {
  contract: ContractInfo;
  threads: ThreadInfo[];
  /** True once the board has draft entries — the card folds itself away so the
   *  deliberation, not the paperwork, owns the space. */
  hasEntries: boolean;
}

/**
 * The Market Maker's drafted contract embedded in the Draft board. A slim
 * always-visible header unfolds into the full document (see
 * contract-document.tsx); it starts open on an empty board and collapses
 * automatically when the first draft entry lands.
 */
export function ContractCard({
  contract,
  threads,
  hasEntries,
}: ContractCardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [expanded, setExpanded] = useState(!hasEntries);

  // Fold away once — when the first entry arrives — without fighting the user
  // if they re-open it afterwards.
  const autoCollapsed = useRef(hasEntries);
  useEffect(() => {
    if (hasEntries && !autoCollapsed.current) {
      autoCollapsed.current = true;
      setExpanded(false);
    }
  }, [hasEntries]);

  const pct = Math.round(Math.max(0, Math.min(1, contract.confidence)) * 100);
  const title = humanizeTaskType(contract.task_type);

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      style={{
        borderRadius: 10,
        marginBottom: 12,
        overflow: "hidden",
        border: "1px solid rgba(139,26,47,0.28)",
        background: dark ? "rgba(139,26,47,0.08)" : "rgba(139,26,47,0.04)",
      }}
    >
      {/* ── Header — always visible, toggles the document ── */}
      <button
        onClick={() => setExpanded((v) => !v)}
        title={expanded ? "Collapse contract" : "Show contract"}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 7,
          padding: "8px 12px",
          background: "none",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <ScrollText
          size={12}
          strokeWidth={2}
          color={BURG_LT}
          style={{ flexShrink: 0 }}
        />
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            color: BURG_LT,
            letterSpacing: "0.09em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            flexShrink: 0,
          }}
        >
          Contract
        </span>
        <span
          style={{
            fontSize: 11.5,
            fontWeight: 600,
            color: t.text,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            minWidth: 0,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          {title}
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 9.5,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          {threads.length > 0 &&
            `${threads.length} thread${threads.length === 1 ? "" : "s"} · `}
          {pct}%
        </span>
        <motion.span
          animate={{ rotate: expanded ? 90 : 0 }}
          transition={{ duration: 0.18 }}
          style={{ display: "flex", flexShrink: 0, color: t.textDim }}
        >
          <ChevronRight size={13} strokeWidth={2.5} />
        </motion.span>
      </button>

      {/* ── The document itself ── */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: "easeInOut" }}
            style={{ overflow: "hidden" }}
          >
            <ContractDocument contract={contract} threads={threads} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
