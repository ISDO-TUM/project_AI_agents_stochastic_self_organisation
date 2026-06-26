"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CornerDownRight, MessageCircle, ChevronDown } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { agentColor } from "@/lib/agent-color";
import { truncate } from "@/lib/blackboard-utils";
import { DraftEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { CitationRing } from "./citation-ring";
import { VoteChip } from "./vote-chip";
import { SystemRow } from "./system-row";

interface ThreadedEntryProps {
  entry: DraftEntry;
  parentContent: string;
  depth: number;
  threshold: number;
  promotedMap: Map<string, number>;
}

const MAX_DEPTH = 4;

export function ThreadedEntry({
  entry,
  parentContent,
  depth,
  threshold,
  promotedMap,
}: ThreadedEntryProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [expanded, setExpanded] = useState(true);
  const indent = Math.min(depth, MAX_DEPTH) * 16;
  const color = agentColor(entry.author_id);
  const promotedRound = promotedMap.get(entry.id);

  if (entry.entry_type === "vote") {
    return (
      <div style={{ marginLeft: indent }}>
        <VoteChip entry={entry} votedEntryPreview={parentContent} />
        {entry.children.map((child) => (
          <ThreadedEntry
            key={child.id}
            entry={child}
            parentContent={truncate(entry.content)}
            depth={depth + 1}
            threshold={threshold}
            promotedMap={promotedMap}
          />
        ))}
      </div>
    );
  }

  if (entry.entry_type === "system") {
    return (
      <div style={{ marginLeft: indent }}>
        <SystemRow entry={entry} />
      </div>
    );
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: entry.is_visible ? 1 : 0.35, x: 0 }}
      transition={{ duration: 0.25 }}
      style={{
        marginLeft: indent,
        marginBottom: 8,
        paddingLeft: 10,
        borderLeft: `2px solid ${color}55`,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
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
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 9,
            fontWeight: 800,
            flexShrink: 0,
          }}
        >
          {(entry.author_name || "?")[0]?.toUpperCase() ?? "?"}
        </span>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: t.text }}>
          {entry.author_name}
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
        <span
          style={{
            fontSize: 9,
            fontWeight: 700,
            color: t.textDim,
            textTransform: "uppercase",
          }}
        >
          reply
        </span>
      </div>
      {parentContent && (
        <div
          style={{
            display: "flex",
            gap: 4,
            fontSize: 10.5,
            color: t.textDim,
            marginBottom: 4,
            fontStyle: "italic",
          }}
        >
          <CornerDownRight
            size={11}
            strokeWidth={2}
            style={{ flexShrink: 0, marginTop: 1 }}
          />
          <span>{parentContent}</span>
        </div>
      )}
      {!entry.is_visible && (
        <div
          style={{
            fontSize: 10,
            color: t.textDim,
            fontStyle: "italic",
            marginBottom: 3,
          }}
        >
          evaporated (R{entry.round})
        </div>
      )}
      <div
        style={{
          fontSize: 12.5,
          color: t.textSub,
          lineHeight: 1.55,
          marginBottom: 6,
        }}
      >
        <MarkdownRenderer content={entry.content} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <CitationRing
          count={entry.citation_count}
          threshold={threshold}
          variant="compact"
          citers={entry.citers}
          promotedRound={promotedRound}
        />
        {entry.children.length > 0 && (
          <button
            onClick={() => setExpanded((e) => !e)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 3,
              fontSize: 10.5,
              color: t.textDim,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
            }}
          >
            <MessageCircle size={10} strokeWidth={2} />
            {entry.children.length}
            <ChevronDown
              size={9}
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
            depth={depth + 1}
            threshold={threshold}
            promotedMap={promotedMap}
          />
        ))}
    </motion.div>
  );
}
