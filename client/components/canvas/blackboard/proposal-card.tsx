"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { MessageCircle, AtSign, ChevronDown } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { agentColor } from "@/lib/agent-color";
import { truncate } from "@/lib/blackboard-utils";
import { DraftEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { CitationRing } from "./citation-ring";
import { ThreadedEntry } from "./reply-thread";

interface ProposalCardProps {
  entry: DraftEntry;
  threshold: number;
  promotedMap: Map<string, number>;
  agents?: { id: string }[];
  promotedAgentIds?: Set<string>;
}

export function ProposalCard({
  entry,
  threshold,
  promotedMap,
  agents = [],
  promotedAgentIds,
}: ProposalCardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [expanded, setExpanded] = useState(true);
  const color = agentColor(entry.author_id, agents, promotedAgentIds);
  const initial = (entry.author_name || "?")[0]?.toUpperCase() ?? "?";
  const promotedRound = promotedMap.get(entry.id);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: entry.is_visible ? 1 : 0.35, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      style={{
        background: dark ? "rgba(139,26,47,0.07)" : "rgba(139,26,47,0.04)",
        border: "1px solid rgba(139,26,47,0.3)",
        borderRadius: 10,
        padding: "11px 14px",
        marginBottom: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 7,
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
          {initial}
        </span>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: t.text }}>
          {entry.author_name}
        </span>
        <span
          style={{
            fontSize: 9,
            fontWeight: 800,
            color: "#8B1A2F",
            background: "rgba(139,26,47,0.13)",
            borderRadius: 4,
            padding: "1.5px 6px",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
          }}
        >
          proposal
        </span>
        {entry.mention_agents.length > 0 && (
          <span
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: 3,
              fontSize: 10,
              color: t.textDim,
            }}
          >
            <AtSign size={10} strokeWidth={2} />
            {entry.mention_agents.length}
          </span>
        )}
      </div>

      {!entry.is_visible && (
        <div
          style={{
            fontSize: 10.5,
            color: t.textDim,
            fontStyle: "italic",
            marginBottom: 4,
          }}
        >
          evaporated (R{entry.round})
        </div>
      )}

      <div
        style={{
          fontSize: 13.5,
          color: t.text,
          lineHeight: 1.6,
          marginBottom: 9,
        }}
      >
        <MarkdownRenderer content={entry.content} fontSize={13.5} />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <CitationRing
          count={entry.citation_count}
          threshold={threshold}
          variant="ring"
          citers={entry.citers}
          promotedRound={promotedRound}
        />
        {entry.children.length > 0 && (
          <button
            onClick={() => setExpanded((e) => !e)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              color: t.textDim,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
            }}
          >
            <MessageCircle size={12} strokeWidth={2} />
            {entry.children.length}
            <ChevronDown
              size={10}
              style={{
                transform: expanded ? "rotate(180deg)" : "none",
                transition: "transform 0.15s",
              }}
            />
          </button>
        )}
      </div>

      {expanded &&
        entry.children.map((child) => (
          <ThreadedEntry
            key={child.id}
            entry={child}
            parentContent={truncate(entry.content)}
            depth={1}
            threshold={threshold}
            promotedMap={promotedMap}
            agents={agents}
            promotedAgentIds={promotedAgentIds}
          />
        ))}
    </motion.div>
  );
}
