"use client";

import { motion, AnimatePresence } from "framer-motion";
import { ReceiptText } from "lucide-react";
import { Agent } from "@/lib/types";
import { agentColor } from "@/lib/agent-color";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT, BURG_GLOW } from "@/lib/theme";

interface AgentDockProps {
  agents: Agent[];
  onSelectAgent: (id: string) => void;
}

/** Fixed horizontal strip above the prompt bar — replaces individually
 *  draggable agent nodes and the Market Maker badge in swarm mode. Market
 *  Maker is a visual-only chip (not clickable, no editable entity behind
 *  it); each agent chip opens the same edit panel a canvas node click does. */
export function AgentDock({ agents, onSelectAgent }: AgentDockProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  return (
    <div
      style={{
        position: "absolute",
        bottom: 100,
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
        padding: "10px 8px",
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
          padding: "0 16px",
          maskImage:
            "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)",
          WebkitMaskImage:
            "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)",
        }}
      >
        {/* Market Maker — visual anchor only, not clickable */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 4,
            flexShrink: 0,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: "50%",
              background: dark
                ? "radial-gradient(circle at 35% 35%, rgba(196,55,79,0.22) 0%, rgba(139,26,47,0.12) 60%, rgba(6,5,12,0.92) 100%)"
                : "radial-gradient(circle at 35% 35%, rgba(196,55,79,0.15) 0%, rgba(139,26,47,0.08) 60%, rgba(240,238,248,0.97) 100%)",
              border: "1.5px solid rgba(139,26,47,0.35)",
              boxShadow: `0 0 14px ${BURG_GLOW}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <ReceiptText size={17} strokeWidth={1.5} color={BURG_LT} />
          </div>
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
            Market Maker
          </span>
        </div>

        <AnimatePresence initial={false}>
          {agents.map((agent) => {
            const color = agentColor(agent.id);
            const initial = (agent.name || "A")[0]?.toUpperCase() ?? "A";
            return (
              <motion.button
                key={agent.id}
                onClick={() => onSelectAgent(agent.id)}
                initial={{ opacity: 0, scale: 0.7 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 4,
                  flexShrink: 0,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                <span
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: "50%",
                    background: `${color}26`,
                    color,
                    border: `1.5px solid ${color}55`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 15,
                    fontWeight: 800,
                  }}
                >
                  {initial}
                </span>
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
              </motion.button>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
