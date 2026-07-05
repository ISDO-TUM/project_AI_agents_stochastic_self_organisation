"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Pin,
  CheckCircle2,
  FileText,
  Copy,
  Check,
  Heart,
  ChevronRight,
  Users,
  AlertTriangle,
} from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT, BURG_DIM } from "@/lib/theme";
import { ConfirmedEntry, DraftEntry } from "@/lib/types";
import { agentColor } from "@/lib/agent-color";
import { MarkdownRenderer } from "@/components/markdown-renderer";

interface ConfirmedCardProps {
  entry: ConfirmedEntry;
  /** The draft entry this confirmed entry was promoted from — resolved by
   *  ConfirmedBoard via source_draft_id. Undefined for anchor/system entries
   *  (no source_draft_id) or if it's no longer in the in-memory draft tree. */
  source?: DraftEntry;
  agents?: { id: string }[];
  promotedAgentIds?: Set<string>;
}

function entryStyle(type: ConfirmedEntry["entry_type"]) {
  if (type === "anchor")
    return {
      icon: <Pin size={11} strokeWidth={2} color={BURG_LT} />,
      label: "ANCHOR",
      color: BURG_LT,
      accentColor: BURG_LT,
      bg: BURG_DIM,
      border: "rgba(139,26,47,0.2)",
    };
  if (type === "finding")
    return {
      icon: <CheckCircle2 size={11} strokeWidth={2} color="#b5860d" />,
      label: "FINDING",
      color: "#b5860d",
      accentColor: "#c49a1a",
      bg: "rgba(181,134,13,0.07)",
      border: "rgba(181,134,13,0.22)",
    };
  return {
    icon: <FileText size={11} strokeWidth={2} color="#7b9ec0" />,
    label: "SYSTEM",
    color: "#7b9ec0",
    accentColor: "#7b9ec0",
    bg: "rgba(123,158,192,0.06)",
    border: "rgba(123,158,192,0.18)",
  };
}

export function ConfirmedCard({
  entry,
  source,
  agents = [],
  promotedAgentIds,
}: ConfirmedCardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const s = entryStyle(entry.entry_type);
  const status = entry.status ?? "confirmed";
  const contested = status === "contested";
  const retracted = status === "retracted";
  const [hovered, setHovered] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showCollaborators, setShowCollaborators] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(entry.content).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const collaborators = source
    ? Array.from(
        new Map(
          (source.citers ?? [])
            .filter((c) => c.agentName !== source.author_name)
            .map((c) => [c.agentName, c] as const),
        ).values(),
      )
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: "relative",
        background: s.bg,
        border: contested
          ? "1px dashed rgba(197,90,17,0.55)"
          : `1px solid ${s.border}`,
        borderLeft: contested
          ? "4px dashed #c55a11"
          : `4px solid ${s.accentColor}`,
        borderRadius: 9,
        padding: "10px 14px",
        marginBottom: 8,
        opacity: retracted ? 0.55 : 1,
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 6,
        }}
      >
        {s.icon}
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            color: s.color,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui",
            textDecoration: retracted ? "line-through" : "none",
          }}
        >
          {s.label}
        </span>
        {entry.entry_type !== "anchor" && (
          <span style={{ fontSize: 10, color: t.textDim }}>
            R{entry.round_confirmed}
          </span>
        )}
        {contested && (
          <span
            style={{
              display: "flex",
              alignItems: "center",
              gap: 3,
              fontSize: 9.5,
              fontWeight: 800,
              color: "#c55a11",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              background: "rgba(197,90,17,0.12)",
              borderRadius: 8,
              padding: "1.5px 7px",
            }}
          >
            <AlertTriangle size={9} strokeWidth={2.5} />
            Contested
          </span>
        )}
        {retracted && (
          <span
            style={{
              fontSize: 9.5,
              fontWeight: 700,
              color: t.textDim,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
            }}
          >
            Retracted
          </span>
        )}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          {entry.citation_count > 0 && (
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: 3,
                fontSize: 10,
                color: t.textDim,
              }}
            >
              <Heart size={9} strokeWidth={2} />
              {entry.citation_count}
            </span>
          )}
          {/* Copy button — fades in on hover */}
          <button
            onClick={handleCopy}
            title={copied ? "Copied!" : "Copy to clipboard"}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 4px",
              display: "flex",
              alignItems: "center",
              color: copied ? s.color : t.textDim,
              opacity: hovered || copied ? 1 : 0,
              transition: "opacity 0.15s, color 0.15s",
              borderRadius: 4,
            }}
          >
            {copied ? (
              <Check size={11} strokeWidth={2.5} />
            ) : (
              <Copy size={11} strokeWidth={1.8} />
            )}
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div style={{ fontSize: 13, color: t.text, lineHeight: 1.6 }}>
        <MarkdownRenderer content={entry.content} />
      </div>

      {/* ── Footer: author / collaborators / references ── */}
      {source && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 8,
            borderTop: `1px solid ${s.border}`,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 18,
                height: 18,
                borderRadius: "50%",
                background: `${agentColor(
                  source.author_id,
                  agents,
                  promotedAgentIds,
                )}26`,
                color: agentColor(source.author_id, agents, promotedAgentIds),
                border: `1px solid ${agentColor(
                  source.author_id,
                  agents,
                  promotedAgentIds,
                )}55`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 9,
                fontWeight: 800,
                flexShrink: 0,
              }}
            >
              {(source.author_name || "?")[0]?.toUpperCase() ?? "?"}
            </span>
            <span style={{ fontSize: 11, color: t.textSub, fontWeight: 600 }}>
              {source.author_name}
            </span>
            {collaborators.length > 0 && (
              <button
                onClick={() => setShowCollaborators((v) => !v)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 3,
                  background: t.pill,
                  border: "none",
                  cursor: "pointer",
                  padding: "1px 6px",
                  borderRadius: 10,
                  fontSize: 10,
                  color: t.textDim,
                  fontWeight: 600,
                }}
                title={`${collaborators.length} collaborator${
                  collaborators.length === 1 ? "" : "s"
                }`}
              >
                <Users size={9} strokeWidth={2} />+{collaborators.length} et al.
                <motion.span
                  animate={{ rotate: showCollaborators ? 90 : 0 }}
                  transition={{ duration: 0.15 }}
                  style={{ display: "flex" }}
                >
                  <ChevronRight size={10} strokeWidth={2.5} />
                </motion.span>
              </button>
            )}
          </div>

          <AnimatePresence initial={false}>
            {showCollaborators && collaborators.length > 0 && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.18 }}
                style={{ overflow: "hidden" }}
              >
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 5,
                    paddingLeft: 24,
                    paddingTop: 2,
                  }}
                >
                  {collaborators.map((c) => (
                    <span
                      key={c.agentName}
                      style={{
                        fontSize: 10,
                        color: t.textDim,
                        background: t.pill,
                        borderRadius: 8,
                        padding: "1.5px 7px",
                      }}
                    >
                      {c.agentName} · R{c.round}
                    </span>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {source.documents_used && source.documents_used.length > 0 && (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                gap: 5,
                paddingLeft: 24,
              }}
            >
              <span
                style={{
                  fontSize: 9.5,
                  fontWeight: 700,
                  color: t.textDim,
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                  fontFamily: "'Space Grotesk', system-ui",
                }}
              >
                References
              </span>
              {source.documents_used.map((doc) => (
                <span
                  key={doc}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 3,
                    fontSize: 10,
                    color: t.textDim,
                    background: t.pill,
                    borderRadius: 8,
                    padding: "1.5px 7px",
                  }}
                >
                  <FileText size={9} strokeWidth={2} />
                  {doc}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
}
