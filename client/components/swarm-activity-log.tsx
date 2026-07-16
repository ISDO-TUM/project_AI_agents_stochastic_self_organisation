"use client";

import { useState } from "react";
import { useTheme } from "@/lib/theme-context";
import {
  getTheme,
  BURG,
  BURG_LT,
  BURG_GLOW,
  SURFACE_DARK_RGB,
} from "@/lib/theme";
import { BlackboardState, DraftEntry } from "@/lib/types";
import {
  Activity,
  Pin,
  CheckCircle2,
  MessageSquare,
  ThumbsUp,
  Zap,
  Trash2,
  X,
  ChevronDown,
} from "lucide-react";

interface ActivityEntry {
  id: string;
  ts: string;
  kind: "confirmed" | "draft" | "cite" | "vote" | "delete" | "system";
  label: string;
  author?: string;
  content?: string;
}

function buildLog(state: BlackboardState): ActivityEntry[] {
  const entries: ActivityEntry[] = [];

  for (const e of state.confirmed) {
    entries.push({
      id: `c-${e.id}`,
      ts: e.created_at,
      kind: e.entry_type === "anchor" ? "confirmed" : "confirmed",
      label:
        e.entry_type === "anchor"
          ? "Anchor posted"
          : `Finding confirmed (R${e.round_confirmed})`,
      content: e.content.slice(0, 80) + (e.content.length > 80 ? "…" : ""),
    });
  }

  function flattenDraft(entry: DraftEntry) {
    entries.push({
      id: `d-${entry.id}`,
      ts: entry.created_at,
      kind: entry.entry_type === "vote" ? "vote" : "draft",
      label:
        entry.entry_type === "vote"
          ? "Vote cast"
          : entry.entry_type === "reply"
            ? "Reply posted"
            : "Proposal posted",
      author: entry.author_name ?? entry.author_id.slice(0, 8),
      content:
        entry.content.slice(0, 80) + (entry.content.length > 80 ? "…" : ""),
    });
    if (!entry.is_visible) {
      entries[entries.length - 1].kind = "delete";
      entries[entries.length - 1].label = "Entry faded (soft-deleted)";
    }
    for (const child of entry.children) flattenDraft(child);
  }

  for (const e of state.draft) flattenDraft(e);

  // sort by ts ascending
  entries.sort((a, b) => a.ts.localeCompare(b.ts));
  return entries;
}

const KIND_ICON: Record<ActivityEntry["kind"], React.ReactNode> = {
  confirmed: <Pin size={11} strokeWidth={2} color={BURG_LT} />,
  draft: <MessageSquare size={11} strokeWidth={2} color="#7b9ec0" />,
  cite: <ThumbsUp size={11} strokeWidth={2} color="#3dba8c" />,
  vote: <Zap size={11} strokeWidth={2} color="#b5860d" />,
  delete: <Trash2 size={11} strokeWidth={2} color="#888" />,
  system: <CheckCircle2 size={11} strokeWidth={2} color="#999" />,
};

const KIND_COLOR: Record<ActivityEntry["kind"], string> = {
  confirmed: BURG_LT,
  draft: "#7b9ec0",
  cite: "#3dba8c",
  vote: "#b5860d",
  delete: "#888",
  system: "#999",
};

interface SwarmActivityLogProps {
  state: BlackboardState;
  runId: string | null;
  onRunIdChange: (id: string | null) => void;
  onSeed: () => void;
  seeding: boolean;
  width?: number;
}

export function SwarmActivityLog({
  state,
  runId,
  onRunIdChange,
  onSeed,
  seeding,
  width = 280,
}: SwarmActivityLogProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [expanded, setExpanded] = useState<string | null>(null);

  const log = buildLog(state);
  const border = t.border;

  function fmtTime(iso: string) {
    try {
      return new Date(iso).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  return (
    <div
      style={{
        width,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: dark
          ? `rgba(${SURFACE_DARK_RGB},0.97)`
          : "rgba(248,246,255,0.98)",
        borderLeft: `1px solid ${border}`,
        backdropFilter: "blur(12px)",
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 14px",
          borderBottom: `1px solid ${border}`,
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexShrink: 0,
        }}
      >
        <Activity size={13} strokeWidth={1.8} color={BURG_LT} />
        <span
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.09em",
            textTransform: "uppercase",
            color: BURG_LT,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            flex: 1,
          }}
        >
          Activity
        </span>
        {runId && (
          <span
            style={{
              fontSize: 9.5,
              color: t.textDim,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {runId.slice(0, 8)}
          </span>
        )}
        {runId && (
          <button
            onClick={() => onRunIdChange(null)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: t.textDim,
              display: "flex",
              alignItems: "center",
              padding: 2,
            }}
            title="Close run"
          >
            <X size={12} strokeWidth={2} />
          </button>
        )}
      </div>

      {/* Stats row */}
      {runId && (
        <div
          style={{
            display: "flex",
            borderBottom: `1px solid ${border}`,
            flexShrink: 0,
          }}
        >
          {[
            {
              label: "Confirmed",
              value: state.confirmed.length,
              color: BURG_LT,
            },
            { label: "Draft", value: state.draft.length, color: "#7b9ec0" },
            { label: "Threads", value: state.threads.length, color: "#3dba8c" },
          ].map(({ label, value, color }) => (
            <div
              key={label}
              style={{
                flex: 1,
                padding: "8px 0",
                textAlign: "center",
                borderRight: `1px solid ${border}`,
              }}
            >
              <div
                style={{
                  fontSize: 16,
                  fontWeight: 800,
                  color,
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                }}
              >
                {value}
              </div>
              <div
                style={{
                  fontSize: 9,
                  color: t.textDim,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                }}
              >
                {label}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* No run */}
      {!runId && (
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 14,
            padding: 20,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: "50%",
              background: `rgba(139,26,47,0.10)`,
              border: `1.5px solid rgba(139,26,47,0.25)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: `0 0 14px ${BURG_GLOW}`,
            }}
          >
            <Activity size={18} strokeWidth={1.5} color={BURG_LT} />
          </div>
          <div
            style={{
              textAlign: "center",
              fontSize: 12,
              color: t.textSub,
              lineHeight: 1.5,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
            }}
          >
            No active run.
            <br />
            Seed test data to preview the blackboard.
          </div>
          <button
            onClick={onSeed}
            disabled={seeding}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "9px 18px",
              background: BURG,
              color: "#fff",
              border: "none",
              borderRadius: 8,
              cursor: seeding ? "not-allowed" : "pointer",
              fontSize: 12,
              fontWeight: 700,
              opacity: seeding ? 0.6 : 1,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              boxShadow: `0 4px 16px ${BURG_GLOW}`,
            }}
          >
            {seeding ? "Seeding…" : "Seed test data"}
          </button>
        </div>
      )}

      {/* Log entries */}
      {runId && (
        <div style={{ flex: 1, overflowY: "auto" }} className="pscroll">
          {log.length === 0 && (
            <div
              style={{
                padding: "24px 0",
                textAlign: "center",
                color: t.textDim,
                fontSize: 12,
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
              }}
            >
              {state.loading ? "Loading…" : "No events yet"}
            </div>
          )}
          {[...log].reverse().map((entry) => (
            <div
              key={entry.id}
              onClick={() =>
                setExpanded((x) => (x === entry.id ? null : entry.id))
              }
              style={{
                padding: "9px 14px",
                borderBottom: `1px solid ${border}`,
                cursor: "pointer",
                background:
                  expanded === entry.id
                    ? dark
                      ? "rgba(255,255,255,0.03)"
                      : "rgba(0,0,0,0.025)"
                    : "transparent",
                transition: "background 0.12s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <div style={{ flexShrink: 0 }}>{KIND_ICON[entry.kind]}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 11.5,
                      fontWeight: 600,
                      color: KIND_COLOR[entry.kind],
                      fontFamily: "'Space Grotesk', system-ui, sans-serif",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {entry.label}
                  </div>
                  {entry.author && (
                    <div
                      style={{
                        fontSize: 9.5,
                        color: t.textDim,
                        fontFamily: "'Space Grotesk', system-ui, sans-serif",
                      }}
                    >
                      {entry.author}
                    </div>
                  )}
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-end",
                    gap: 2,
                    flexShrink: 0,
                  }}
                >
                  <span
                    style={{
                      fontSize: 9.5,
                      color: t.textDim,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {fmtTime(entry.ts)}
                  </span>
                  {entry.content && (
                    <ChevronDown
                      size={10}
                      strokeWidth={2}
                      color={t.textDim}
                      style={{
                        transform:
                          expanded === entry.id
                            ? "rotate(180deg)"
                            : "rotate(0deg)",
                        transition: "transform 0.15s",
                      }}
                    />
                  )}
                </div>
              </div>
              {expanded === entry.id && entry.content && (
                <div
                  style={{
                    marginTop: 7,
                    marginLeft: 18,
                    fontSize: 11,
                    color: t.textSub,
                    lineHeight: 1.5,
                    fontFamily: "'Space Grotesk', system-ui, sans-serif",
                    borderLeft: `2px solid ${KIND_COLOR[entry.kind]}`,
                    paddingLeft: 8,
                    opacity: 0.85,
                  }}
                >
                  {entry.content}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
