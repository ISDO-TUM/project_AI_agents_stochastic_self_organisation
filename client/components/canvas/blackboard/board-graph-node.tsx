"use client";

import { motion } from "framer-motion";
import {
  Lightbulb,
  Reply,
  ThumbsUp,
  Settings2,
  CheckCircle2,
  EyeOff,
  Maximize2,
} from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { truncate } from "@/lib/blackboard-utils";
import {
  GraphAgentHub,
  GraphEntryNode,
  HUB_RADIUS,
} from "@/lib/board-graph-layout";
import { AgentTrustPanel } from "./agent-trust-panel";

const GOLD = "#b5860d";

// ─── Agent hub ───────────────────────────────────────────────────────────

interface GraphHubNodeProps {
  hub: GraphAgentHub;
  color: string;
  opacity: number;
  selected: boolean;
  onOpenChange: (open: boolean) => void;
}

export function GraphHubNode({
  hub,
  color,
  opacity,
  selected,
  onOpenChange,
}: GraphHubNodeProps) {
  const { dark } = useTheme();
  const initial = (hub.name || "?")[0]?.toUpperCase() ?? "?";
  const glowSize = 6 + Math.min(hub.citationTotal, 12) * 1.4;

  return (
    <motion.div
      layout
      initial={false}
      animate={{ opacity, scale: selected ? 1.08 : 1 }}
      transition={{ duration: 0.2 }}
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        left: hub.x - HUB_RADIUS,
        top: hub.y - HUB_RADIUS,
        width: HUB_RADIUS * 2,
        height: HUB_RADIUS * 2,
        zIndex: 6,
      }}
    >
      <AgentTrustPanel
        agentId={hub.id}
        agentName={hub.name}
        role={null}
        citationCount={hub.citationTotal}
        onOpenChange={onOpenChange}
        trigger={
          <button
            title={
              hub.entryCount > 0
                ? `${hub.name} — ${hub.entryCount} contribution${
                    hub.entryCount === 1 ? "" : "s"
                  }`
                : hub.citesGiven > 0
                  ? `${hub.name} — voted/cited ${hub.citesGiven}× without posting own contributions`
                  : hub.name
            }
            style={{
              width: "100%",
              height: "100%",
              borderRadius: "50%",
              border: `2px solid ${color}`,
              background: dark ? `${color}26` : `${color}1f`,
              boxShadow: selected
                ? `0 0 0 3px ${color}55, 0 0 ${glowSize + 10}px ${color}66`
                : `0 0 ${glowSize}px ${color}44`,
              color,
              fontSize: 18,
              fontWeight: 800,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "box-shadow 0.2s, transform 0.15s",
            }}
          >
            {initial}
          </button>
        }
      />

      {hub.confirmedCount > 0 && (
        <span
          style={{
            position: "absolute",
            top: -4,
            right: -4,
            width: 17,
            height: 17,
            borderRadius: "50%",
            background: GOLD,
            color: "#1a1305",
            fontSize: 9,
            fontWeight: 800,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `1.5px solid ${dark ? "#0b0a12" : "#faf7f0"}`,
            pointerEvents: "none",
          }}
        >
          {hub.confirmedCount}
        </span>
      )}

      <div
        style={{
          position: "absolute",
          top: HUB_RADIUS * 2 + 6,
          left: "50%",
          transform: "translateX(-50%)",
          whiteSpace: "nowrap",
          fontSize: 10.5,
          fontWeight: 700,
          color: dark ? "#eceaf5" : "#18161f",
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          pointerEvents: "none",
          maxWidth: 120,
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {hub.name}
      </div>
    </motion.div>
  );
}

// ─── Entry node (proposal / reply / vote / system) ──────────────────────

interface GraphEntryCardProps {
  node: GraphEntryNode;
  color: string;
  opacity: number;
  selected: boolean;
  threshold: number;
  onToggleSelect: () => void;
  onExpand: () => void;
}

export function GraphEntryCard({
  node,
  color,
  opacity,
  selected,
  threshold,
  onToggleSelect,
  onExpand,
}: GraphEntryCardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const { entry } = node;

  const baseStyle: React.CSSProperties = {
    position: "absolute",
    left: node.x,
    top: node.y,
    width: node.w,
    zIndex: selected ? 5 : 3,
  };

  if (entry.entry_type === "vote") {
    return (
      <motion.div
        layout
        initial={false}
        animate={{ opacity, scale: selected ? 1.05 : 1 }}
        whileHover={{ scale: 1.06 }}
        transition={{ duration: 0.2 }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect();
        }}
        style={{
          ...baseStyle,
          height: node.h,
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "0 10px",
          borderRadius: 100,
          background: dark ? "rgba(61,186,140,0.10)" : "rgba(61,186,140,0.08)",
          border: `1.5px solid ${
            selected ? "#3dba8c" : "rgba(61,186,140,0.4)"
          }`,
          cursor: "pointer",
          boxShadow: selected ? "0 0 12px rgba(61,186,140,0.35)" : "none",
        }}
      >
        <ThumbsUp size={11} strokeWidth={2} color="#3dba8c" />
        <span
          style={{
            fontSize: 10.5,
            fontWeight: 700,
            color: t.text,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {entry.author_name}
        </span>
        <span
          style={{
            fontSize: 9,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
            marginLeft: "auto",
          }}
        >
          R{entry.round}
        </span>
      </motion.div>
    );
  }

  if (entry.entry_type === "system") {
    return (
      <motion.div
        layout
        initial={false}
        animate={{ opacity: opacity * 0.85 }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect();
        }}
        title={entry.content}
        style={{
          ...baseStyle,
          height: node.h,
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "0 8px",
          borderRadius: 7,
          background: dark
            ? "rgba(123,158,192,0.08)"
            : "rgba(123,158,192,0.07)",
          border: `1px dashed ${
            selected ? "#7b9ec0" : "rgba(123,158,192,0.4)"
          }`,
          cursor: "pointer",
        }}
      >
        <Settings2 size={10} strokeWidth={2} color="#7b9ec0" />
        <span
          style={{
            fontSize: 9.5,
            color: t.textDim,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {truncate(entry.content, 40)}
        </span>
      </motion.div>
    );
  }

  // Graph declutter: above the density gate, low-significance proposal/reply
  // entries collapse to a small pill instead of a full card — nothing is
  // hidden, just smaller; full content is one click away via the expand modal.
  if (node.compact && (entry.entry_type === "proposal" || entry.entry_type === "reply")) {
    const PillIcon = entry.entry_type === "proposal" ? Lightbulb : Reply;
    return (
      <motion.div
        layout
        initial={false}
        animate={{ opacity, scale: selected ? 1.06 : 1 }}
        whileHover={{ scale: 1.07 }}
        transition={{ duration: 0.2 }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect();
        }}
        style={{
          ...baseStyle,
          height: node.h,
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "0 8px",
          borderRadius: 100,
          background: dark ? `${color}12` : `${color}0d`,
          border: `1.5px solid ${
            node.confirmedRound !== null ? GOLD : selected ? color : `${color}45`
          }`,
          cursor: "pointer",
          boxShadow: selected ? `0 0 10px ${color}45` : "none",
        }}
      >
        <PillIcon size={10} strokeWidth={2} color={`${color}cc`} style={{ flexShrink: 0 }} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: t.text,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
            minWidth: 0,
          }}
        >
          {entry.author_name}
        </span>
        <span
          style={{
            fontSize: 8.5,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
            flexShrink: 0,
          }}
        >
          R{entry.round}
        </span>
        {entry.citation_count > 0 && (
          <span style={{ fontSize: 8.5, color: t.textDim, flexShrink: 0 }}>
            ♡{entry.citation_count}
          </span>
        )}
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onExpand();
          }}
          title="Expand full content"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 2,
            margin: -2,
            display: "flex",
            color: t.textDim,
            flexShrink: 0,
          }}
        >
          <Maximize2 size={9} strokeWidth={2} />
        </button>
      </motion.div>
    );
  }

  // proposal / reply — the main "contribution card"
  const isProposal = entry.entry_type === "proposal";
  const Icon = isProposal ? Lightbulb : Reply;
  const preview = truncate(entry.content, 128);
  const cardBg = dark ? "rgba(139,26,47,0.08)" : "rgba(139,26,47,0.045)";
  const fadeBg = dark ? "rgba(15,13,22,0.94)" : "rgba(248,246,255,0.96)";

  return (
    <motion.div
      layout
      initial={false}
      animate={{ opacity, scale: selected ? 1.04 : 1 }}
      whileHover={{ scale: 1.03, zIndex: 8 }}
      transition={{ duration: 0.2 }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        onToggleSelect();
      }}
      style={{
        ...baseStyle,
        height: node.h,
        overflow: "hidden",
        borderRadius: 10,
        background: cardBg,
        border: `1.5px solid ${
          node.confirmedRound !== null ? GOLD : selected ? color : `${color}55`
        }`,
        boxShadow:
          node.confirmedRound !== null
            ? `0 0 14px rgba(181,134,13,0.35)`
            : selected
              ? `0 0 14px ${color}55`
              : dark
                ? "0 3px 12px rgba(0,0,0,0.35)"
                : "0 3px 10px rgba(0,0,0,0.08)",
        cursor: "pointer",
        padding: "7px 9px 6px",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          marginBottom: 3,
        }}
      >
        <span
          style={{
            width: 16,
            height: 16,
            borderRadius: "50%",
            background: `${color}26`,
            color,
            border: `1px solid ${color}55`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 8.5,
            fontWeight: 800,
            flexShrink: 0,
          }}
        >
          {(entry.author_name || "?")[0]?.toUpperCase() ?? "?"}
        </span>
        <span
          style={{
            fontSize: 10.5,
            fontWeight: 700,
            color: t.text,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
            minWidth: 0,
          }}
        >
          {entry.author_name}
        </span>
        <Icon
          size={10}
          strokeWidth={2}
          color={`${color}cc`}
          style={{ flexShrink: 0 }}
        />
        <span
          style={{
            fontSize: 8.5,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
            flexShrink: 0,
          }}
        >
          R{entry.round}
        </span>
        {!entry.is_visible && (
          <EyeOff
            size={10}
            strokeWidth={2}
            color={t.textDim}
            style={{ flexShrink: 0 }}
          />
        )}
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            // Expansion is not selection — keep the card's own onClick out of it.
            e.stopPropagation();
            onExpand();
          }}
          title="Expand full content"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 3,
            margin: -3,
            display: "flex",
            color: t.textDim,
            flexShrink: 0,
          }}
        >
          <Maximize2 size={10} strokeWidth={2} />
        </button>
      </div>

      <div
        style={{
          position: "relative",
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            fontSize: 11,
            color: dark ? "#eceaf5" : "#18161f",
            lineHeight: 1.42,
          }}
        >
          {preview}
        </div>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            height: 16,
            background: `linear-gradient(transparent, ${fadeBg})`,
            pointerEvents: "none",
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 3,
          flexShrink: 0,
        }}
      >
        {node.confirmedRound !== null ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              fontSize: 9,
              fontWeight: 700,
              color: GOLD,
            }}
          >
            <CheckCircle2 size={10} strokeWidth={2} />
            Confirmed R{node.confirmedRound}
          </span>
        ) : (
          <span style={{ fontSize: 9, color: t.textDim }}>
            {entry.citation_count}/{threshold} cited
          </span>
        )}
      </div>
    </motion.div>
  );
}
