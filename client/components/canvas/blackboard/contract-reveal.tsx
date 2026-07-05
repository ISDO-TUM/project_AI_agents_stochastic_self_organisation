"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ScrollText, X } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT } from "@/lib/theme";
import { ContractInfo, ThreadInfo } from "@/lib/types";
import { ContractDocument } from "./contract-document";

interface ContractRevealProps {
  open: boolean;
  contract: ContractInfo;
  threads: ThreadInfo[];
  onClose: () => void;
}

/**
 * The Market Maker's contract as a centred overlay — opened by clicking the
 * Market Maker chip in the agent dock. Same document as the Draft board's
 * inline card; same dismissal manners as FinalAnswerReveal (click-away, ✕,
 * Escape).
 */
export function ContractReveal({
  open,
  contract,
  threads,
  onClose,
}: ContractRevealProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="contract-reveal"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
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
            initial={{ opacity: 0, y: 18, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 280, damping: 26 }}
            style={{
              width: "min(560px, 94vw)",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              background: dark
                ? "rgba(14,11,18,0.97)"
                : "rgba(255,253,248,0.99)",
              border: "1px solid rgba(139,26,47,0.4)",
              borderRadius: 16,
              overflow: "hidden",
              boxShadow: "0 30px 90px rgba(0,0,0,0.5)",
            }}
          >
            {/* ── Header ── */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 9,
                padding: "12px 16px",
                background: dark
                  ? "rgba(139,26,47,0.18)"
                  : "rgba(139,26,47,0.07)",
                borderBottom: "1px solid rgba(139,26,47,0.28)",
                flexShrink: 0,
              }}
            >
              <ScrollText size={14} strokeWidth={2} color={BURG_LT} />
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  color: BURG_LT,
                  letterSpacing: "0.11em",
                  textTransform: "uppercase",
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                }}
              >
                The Contract
              </span>
              <button
                onClick={onClose}
                title="Dismiss (Esc)"
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

            {/* ── The document ── */}
            <div style={{ overflowY: "auto" }} className="pscroll">
              <ContractDocument contract={contract} threads={threads} />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
