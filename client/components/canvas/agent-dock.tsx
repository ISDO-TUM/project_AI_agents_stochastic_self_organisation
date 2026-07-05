"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ReceiptText } from "lucide-react";
import { Agent, ContractInfo, ThreadInfo } from "@/lib/types";
import { agentColor } from "@/lib/agent-color";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT } from "@/lib/theme";
import { AgentTrustPanel } from "./blackboard/agent-trust-panel";
import { ContractReveal } from "./blackboard/contract-reveal";

interface AgentDockProps {
  agents: Agent[];
  onSelectAgent: (id: string) => void;
  bottom: number;
  onHeightChange?: (h: number) => void;
  /** Trust vectors keyed by agent ID — shown in a popover on each chip. */
  trustVectors?: Record<
    string,
    { domain: string; trust_score: number; runs_participated: number }[]
  >;
  /** Agents with a promoted contribution — always rendered gold. */
  promotedAgentIds?: Set<string>;
  /** Agent IDs whose turn is in flight — pulse a ring around their chip. */
  respondingIds?: string[];
  /** The Market Maker's drafted contract — clicking its chip reopens it. */
  contract?: ContractInfo | null;
  /** Threads for the contract's Schedule of Work. */
  threads?: ThreadInfo[];
  /** True while the Market Maker is drafting — pulses its chip like a
   *  responding agent's. */
  marketMakerBusy?: boolean;
}

/** Fixed horizontal strip above the prompt bar — replaces individually
 *  draggable agent nodes in swarm mode. The Market Maker leads the dock as a
 *  participant: it pulses while drafting the contract and, once the contract
 *  exists, clicking it reopens the document. Each agent chip opens the same
 *  edit panel a canvas node click does. */
export function AgentDock({
  agents,
  onSelectAgent,
  bottom,
  onHeightChange,
  trustVectors = {},
  promotedAgentIds,
  respondingIds = [],
  contract = null,
  threads = [],
  marketMakerBusy = false,
}: AgentDockProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const dockRef = useRef<HTMLDivElement>(null);
  const [contractOpen, setContractOpen] = useState(false);

  useEffect(() => {
    const el = dockRef.current;
    if (!el || !onHeightChange) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const height =
        entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height;
      if (height) onHeightChange(height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [onHeightChange]);

  const mmClickable = contract != null;

  return (
    <div
      ref={dockRef}
      style={{
        position: "absolute",
        bottom,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 20,
        maxWidth: "min(720px, 90vw)",
        borderRadius: 20,
        background: dark ? "rgba(8,6,16,0.85)" : "rgba(255,253,255,0.9)",
        backdropFilter: "blur(24px)",
        border: `1px solid ${t.borderHi}`,
        boxShadow: dark
          ? "0 12px 40px rgba(0,0,0,0.5)"
          : "0 8px 28px rgba(0,0,0,0.12)",
        padding: "2px 8px",
      }}
    >
      <div
        className="pscroll"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          overflowX: "auto",
          overflowY: "hidden",
          // Vertical padding gives the chips' pulse ring (scales to 1.5×) room
          // to expand before `overflowY: hidden` clips it.
          padding: "12px 16px",
          maskImage:
            "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)",
          WebkitMaskImage:
            "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)",
        }}
      >
        {/* ── Market Maker — drafts the contract; click reopens it ── */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 4,
            flexShrink: 0,
          }}
        >
          <button
            onClick={mmClickable ? () => setContractOpen(true) : undefined}
            disabled={!mmClickable}
            title={
              mmClickable
                ? "View the drafted contract"
                : marketMakerBusy
                  ? "Drafting the contract…"
                  : "Market Maker"
            }
            style={{
              position: "relative",
              display: "inline-flex",
              background: "none",
              border: "none",
              padding: 0,
              cursor: mmClickable ? "pointer" : "default",
            }}
          >
            {marketMakerBusy && (
              <motion.span
                aria-hidden
                initial={{ opacity: 0.7, scale: 1 }}
                animate={{ opacity: [0.7, 0, 0.7], scale: [1, 1.5, 1] }}
                transition={{
                  duration: 1.3,
                  repeat: Infinity,
                  ease: "easeOut",
                }}
                style={{
                  position: "absolute",
                  inset: -3,
                  borderRadius: "50%",
                  border: `2px solid ${BURG_LT}`,
                  pointerEvents: "none",
                }}
              />
            )}
            <motion.span
              whileHover={mmClickable ? { scale: 1.08 } : undefined}
              whileTap={mmClickable ? { scale: 0.94 } : undefined}
              style={{
                width: 40,
                height: 40,
                borderRadius: "50%",
                background: dark
                  ? "radial-gradient(circle at 35% 35%, rgba(196,55,79,0.22) 0%, rgba(139,26,47,0.12) 60%, rgba(6,5,12,0.92) 100%)"
                  : "radial-gradient(circle at 35% 35%, rgba(196,55,79,0.15) 0%, rgba(139,26,47,0.08) 60%, rgba(240,238,248,0.97) 100%)",
                border: "1.5px solid rgba(139,26,47,0.35)",
                // Only glow while actively drafting — no permanent halo, so it
                // sits level with the agent chips beside it.
                boxShadow: marketMakerBusy
                  ? `0 0 18px ${BURG_LT}aa`
                  : undefined,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {/* The quill wiggles while the contract is being written. */}
              <motion.span
                animate={
                  marketMakerBusy
                    ? { rotate: [0, -8, 6, -4, 0], y: [0, -1, 0.5, 0] }
                    : { rotate: 0, y: 0 }
                }
                transition={
                  marketMakerBusy
                    ? { duration: 1.1, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0.2 }
                }
                style={{ display: "flex" }}
              >
                <ReceiptText size={17} strokeWidth={1.5} color={BURG_LT} />
              </motion.span>
            </motion.span>
          </button>
          <span
            style={{
              fontSize: 8.5,
              fontWeight: 800,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: BURG_LT,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              whiteSpace: "nowrap",
            }}
          >
            {marketMakerBusy ? "Drafting…" : "Market Maker"}
          </span>
        </div>

        <AnimatePresence initial={false}>
          {agents.map((agent) => {
            const color = agentColor(agent.id, agents, promotedAgentIds);
            const initial = (agent.name || "A")[0]?.toUpperCase() ?? "A";
            const tv = trustVectors[agent.id] ?? [];
            const responding = respondingIds.includes(agent.id);
            const chipContent = (
              <span
                style={{
                  position: "relative",
                  display: "inline-flex",
                  flexShrink: 0,
                }}
              >
                {responding && (
                  <motion.span
                    aria-hidden
                    initial={{ opacity: 0.7, scale: 1 }}
                    animate={{ opacity: [0.7, 0, 0.7], scale: [1, 1.5, 1] }}
                    transition={{
                      duration: 1.3,
                      repeat: Infinity,
                      ease: "easeOut",
                    }}
                    style={{
                      position: "absolute",
                      inset: -3,
                      borderRadius: "50%",
                      border: `2px solid ${color}`,
                      pointerEvents: "none",
                    }}
                  />
                )}
                <span
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: "50%",
                    background: `${color}26`,
                    color,
                    border: `1.5px solid ${color}55`,
                    boxShadow: responding ? `0 0 14px ${color}aa` : undefined,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 15,
                    fontWeight: 800,
                    cursor: "pointer",
                  }}
                >
                  {initial}
                </span>
              </span>
            );
            return (
              <motion.div
                key={agent.id}
                initial={{ opacity: 0, scale: 0.7 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 4,
                  flexShrink: 0,
                }}
              >
                {tv.length > 0 ? (
                  <AgentTrustPanel
                    agentId={agent.id}
                    agentName={agent.name}
                    role={null}
                    citationCount={0}
                    trigger={chipContent}
                  />
                ) : (
                  <button
                    onClick={() => onSelectAgent(agent.id)}
                    style={{
                      background: "none",
                      border: "none",
                      padding: 0,
                      cursor: "pointer",
                    }}
                  >
                    {chipContent}
                  </button>
                )}
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: t.text,
                    whiteSpace: "nowrap",
                    maxWidth: 64,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {agent.name}
                </span>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {contract && (
        <ContractReveal
          open={contractOpen}
          contract={contract}
          threads={threads}
          onClose={() => setContractOpen(false)}
        />
      )}
    </div>
  );
}
