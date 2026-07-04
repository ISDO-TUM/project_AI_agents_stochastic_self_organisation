"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  Copy,
  Heart,
  Sparkles,
  X,
} from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { ConfirmedEntry, Ratification } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";

const GOLD = "#b5860d";
const AMBER = "#c55a11";

interface FinalAnswerRevealProps {
  open: boolean;
  /** The original user prompt, shown for context above the answer. */
  prompt: string;
  /** The synthesised answer (markdown). */
  answer: string;
  /** Confirmed findings the answer was synthesised from. */
  findings: ConfirmedEntry[];
  /** The takers' vote on `answer` (ratified synthesis). Null if it didn't run. */
  ratification?: Ratification | null;
  onClose: () => void;
}

/**
 * The completion "reveal" — a centred, animated overlay that presents the
 * synthesised answer the moment a swarm run finishes. The prompt sits above it
 * for context, the supporting confirmed findings collapse below it, and the
 * whole thing is dismissible (click-away, ✕, or Escape) back to the board, where
 * the answer also persists on the Confirmed panel.
 */
export function FinalAnswerReveal({
  open,
  prompt,
  answer,
  findings,
  ratification = null,
  onClose,
}: FinalAnswerRevealProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [copied, setCopied] = useState(false);
  const [showFindings, setShowFindings] = useState(false);

  // Escape closes — matches the app's other dismissible surfaces.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(answer).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="final-answer-reveal"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22 }}
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
              width: "min(640px, 94vw)",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              background: dark
                ? "rgba(12,10,4,0.97)"
                : "rgba(255,253,245,0.99)",
              border: "1px solid rgba(181,134,13,0.4)",
              borderRadius: 18,
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
                padding: "13px 18px",
                background: dark
                  ? "rgba(181,134,13,0.16)"
                  : "rgba(181,134,13,0.08)",
                borderBottom: "1px solid rgba(181,134,13,0.28)",
                flexShrink: 0,
              }}
            >
              <Sparkles size={15} strokeWidth={2} color={GOLD} />
              <span
                style={{
                  fontSize: 12.5,
                  fontWeight: 800,
                  color: GOLD,
                  letterSpacing: "0.11em",
                  textTransform: "uppercase",
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                }}
              >
                Final answer
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
                  title={copied ? "Copied!" : "Copy answer"}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: "4px 8px",
                    borderRadius: 6,
                    color: copied ? "#3dba8c" : GOLD,
                    fontSize: 11,
                    fontFamily: "'Space Grotesk', system-ui, sans-serif",
                    fontWeight: 600,
                  }}
                >
                  {copied ? (
                    <Check size={13} strokeWidth={2.5} />
                  ) : (
                    <Copy size={13} strokeWidth={1.8} />
                  )}
                  {copied ? "Copied" : "Copy"}
                </button>
                <button
                  onClick={onClose}
                  title="Dismiss (Esc)"
                  style={{
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
            </div>

            {/* ── Body ── */}
            <div
              style={{ overflowY: "auto", padding: "16px 20px 20px" }}
              className="pscroll"
            >
              {prompt.trim() && (
                <div style={{ marginBottom: 14 }}>
                  <div
                    style={{
                      fontSize: 9.5,
                      fontWeight: 700,
                      color: t.textDim,
                      letterSpacing: "0.1em",
                      textTransform: "uppercase",
                      fontFamily: "'Space Grotesk', system-ui, sans-serif",
                      marginBottom: 5,
                    }}
                  >
                    You asked
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: t.textDim,
                      lineHeight: 1.5,
                      paddingLeft: 11,
                      borderLeft: `2px solid rgba(181,134,13,0.4)`,
                      fontStyle: "italic",
                    }}
                  >
                    {prompt}
                  </div>
                </div>
              )}

              {/* The answer itself — the hero of the overlay. */}
              <div
                style={{
                  fontSize: 14.5,
                  color: t.text,
                  lineHeight: 1.65,
                }}
              >
                <MarkdownRenderer content={answer} />
              </div>

              {/* ── Ratification badge (ratified synthesis) ── */}
              {ratification && ratification.approved && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    marginTop: 10,
                    fontSize: 10.5,
                    fontWeight: 700,
                    color: GOLD,
                  }}
                >
                  <CheckCircle2 size={11} strokeWidth={2} />
                  Ratified by {ratification.approvals}/{ratification.voters}{" "}
                  takers
                </div>
              )}
              {ratification && !ratification.approved && (
                <div
                  style={{
                    marginTop: 10,
                    padding: "8px 12px",
                    background: "rgba(197,90,17,0.09)",
                    border: "1px solid rgba(197,90,17,0.3)",
                    borderRadius: 8,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                      fontSize: 10.5,
                      fontWeight: 800,
                      color: AMBER,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                      marginBottom: ratification.objections.length ? 5 : 0,
                    }}
                  >
                    <AlertTriangle size={11} strokeWidth={2.5} />
                    Contested synthesis ({ratification.approvals}/
                    {ratification.voters} approved)
                  </div>
                  {ratification.objections.length > 0 && (
                    <ul
                      style={{
                        margin: 0,
                        paddingLeft: 16,
                        fontSize: 11.5,
                        color: t.textSub,
                        lineHeight: 1.5,
                      }}
                    >
                      {ratification.objections.map((o, i) => (
                        <li key={i}>{o}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {/* ── Supporting findings (collapsible) ── */}
              {findings.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <button
                    onClick={() => setShowFindings((v) => !v)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: "4px 0",
                      color: GOLD,
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: "0.04em",
                      fontFamily: "'Space Grotesk', system-ui, sans-serif",
                    }}
                  >
                    <motion.span
                      animate={{ rotate: showFindings ? 90 : 0 }}
                      transition={{ duration: 0.18 }}
                      style={{ display: "flex" }}
                    >
                      <ChevronRight size={13} strokeWidth={2.5} />
                    </motion.span>
                    {findings.length} supporting finding
                    {findings.length === 1 ? "" : "s"}
                  </button>

                  <AnimatePresence initial={false}>
                    {showFindings && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.22 }}
                        style={{ overflow: "hidden" }}
                      >
                        <div style={{ paddingTop: 8 }}>
                          {findings.map((f) => (
                            <div
                              key={f.id}
                              style={{
                                background: "rgba(181,134,13,0.06)",
                                border: "1px solid rgba(181,134,13,0.2)",
                                borderLeft: `3px solid ${GOLD}`,
                                borderRadius: 8,
                                padding: "8px 12px",
                                marginBottom: 7,
                              }}
                            >
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 6,
                                  marginBottom: 4,
                                }}
                              >
                                <CheckCircle2
                                  size={11}
                                  strokeWidth={2}
                                  color={GOLD}
                                />
                                <span
                                  style={{
                                    fontSize: 9.5,
                                    fontWeight: 800,
                                    color: GOLD,
                                    letterSpacing: "0.07em",
                                    textTransform: "uppercase",
                                    fontFamily:
                                      "'Space Grotesk', system-ui, sans-serif",
                                  }}
                                >
                                  Finding
                                </span>
                                <span
                                  style={{ fontSize: 9.5, color: t.textDim }}
                                >
                                  R{f.round_confirmed}
                                </span>
                                {f.citation_count > 0 && (
                                  <span
                                    style={{
                                      marginLeft: "auto",
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 3,
                                      fontSize: 9.5,
                                      color: t.textDim,
                                    }}
                                  >
                                    <Heart size={9} strokeWidth={2} />
                                    {f.citation_count}
                                  </span>
                                )}
                              </div>
                              <div
                                style={{
                                  fontSize: 12,
                                  color: t.text,
                                  lineHeight: 1.5,
                                }}
                              >
                                <MarkdownRenderer content={f.content} />
                              </div>
                            </div>
                          ))}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
