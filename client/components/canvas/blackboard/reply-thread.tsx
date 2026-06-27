"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MessageCircle, ChevronDown } from "lucide-react";
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
  const hasChildren = entry.children.length > 0;

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
    <div style={{ marginLeft: indent, marginBottom: 5 }}>
      {/* ── Card ── */}
      <motion.div
        layout
        initial={{ opacity: 0, x: -4 }}
        animate={{ opacity: entry.is_visible ? 1 : 0.3, x: 0 }}
        transition={{ duration: 0.2 }}
        style={{
          borderLeft: `3px solid ${color}66`,
          borderRadius: "0 8px 8px 0",
          background: dark ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.02)",
          padding: "6px 10px",
        }}
      >
        {/* ── Header ── */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}
        >
          <span
            style={{
              width: 14,
              height: 14,
              borderRadius: "50%",
              background: `${color}33`,
              color,
              border: `1px solid ${color}55`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 8,
              fontWeight: 800,
              flexShrink: 0,
            }}
          >
            {(entry.author_name || "?")[0]?.toUpperCase() ?? "?"}
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: t.text }}>
            {entry.author_name}
          </span>
          <span
            style={{ fontSize: 9, color: `${color}99`, fontFamily: "'JetBrains Mono', monospace" }}
          >
            R{entry.round}
          </span>
          {hasChildren && (
            <button
              onClick={() => setExpanded((e) => !e)}
              style={{
                marginLeft: "auto",
                display: "flex",
                alignItems: "center",
                gap: 3,
                fontSize: 9.5,
                color: t.textDim,
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "1px 4px",
                borderRadius: 4,
              }}
            >
              <MessageCircle size={9} strokeWidth={2} />
              <span>{entry.children.length}</span>
              <ChevronDown
                size={8}
                style={{
                  transform: expanded ? "rotate(180deg)" : "none",
                  transition: "transform 0.15s",
                }}
              />
            </button>
          )}
        </div>

        {/* ── Parent quote ── */}
        {parentContent && (
          <div
            style={{
              borderLeft: `2px solid ${color}44`,
              background: dark ? `${color}0e` : `${color}09`,
              borderRadius: "0 4px 4px 0",
              padding: "3px 8px",
              marginBottom: 5,
            }}
          >
            <span
              style={{ fontSize: 10.5, color: t.textSub, lineHeight: 1.4, display: "block" }}
            >
              {parentContent}
            </span>
          </div>
        )}

        {/* ── Evaporated ── */}
        {!entry.is_visible && (
          <div
            style={{ fontSize: 9.5, color: t.textDim, fontStyle: "italic", marginBottom: 3 }}
          >
            evaporated · R{entry.round}
          </div>
        )}

        {/* ── Body ── */}
        <div
          style={{ fontSize: 12, color: dark ? "#eceaf5" : "#18161f", lineHeight: 1.55, marginBottom: 5 }}
        >
          <MarkdownRenderer content={entry.content} />
        </div>

        {/* ── Footer ── */}
        <CitationRing
          count={entry.citation_count}
          threshold={threshold}
          variant="compact"
          citers={entry.citers}
          promotedRound={promotedRound}
        />
      </motion.div>

      {/* ── Nested children with animated expand + connector line ── */}
      <AnimatePresence>
        {hasChildren && expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18, ease: "easeInOut" }}
            style={{ overflow: "hidden", paddingLeft: 10, position: "relative", marginTop: 3 }}
          >
            {/* Vertical connector */}
            <div
              style={{
                position: "absolute",
                left: 5,
                top: 2,
                bottom: 6,
                width: 1,
                background: `${color}33`,
                borderRadius: 1,
              }}
            />
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
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
