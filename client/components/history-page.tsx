"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchAgents,
  fetchHistoryMessages,
  fetchHistoryTrials,
} from "@/lib/api";
import { Agent, HistoryMessage, HistoryTrial } from "@/lib/types";
import { BURG_LT, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { agentColor } from "@/lib/agent-color";
import { LIcon } from "@/lib/icons";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface HistoryPageProps {
  onBack: () => void;
}

const ALL = "all";
const MONO = "var(--font-jetbrains-mono), ui-monospace, monospace";
const SERIF = "var(--font-playfair), Georgia, serif";

/** Muted tints for message-type tags — hashed so unknown types stay stable. */
const TYPE_PALETTE = [
  "#7b9ec0",
  "#3dba8c",
  "#9b7bc0",
  "#d97757",
  "#5fb8d9",
  "#b5860d",
  "#b07a9e",
];

function typeColor(type: string): string {
  let hash = 0;
  for (let i = 0; i < type.length; i++) {
    hash = (hash * 31 + type.charCodeAt(i)) >>> 0;
  }
  return TYPE_PALETTE[hash % TYPE_PALETTE.length];
}

function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (s.includes("complete") || s.includes("done") || s.includes("success"))
    return "#3dba8c";
  if (s.includes("fail") || s.includes("error")) return "#C4374F";
  return "#b5860d";
}

function fmtClock(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function fmtDay(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString([], {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

function fmtFull(iso: string): string {
  try {
    return new Date(iso).toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** From→to agent chips joined by a gradient signal path with an arrowhead. */
function RouteRibbon({
  message,
  agents,
  large,
  textColor,
}: {
  message: HistoryMessage;
  agents: Agent[];
  large?: boolean;
  textColor: string;
}) {
  const fromC = message.fromAgentId
    ? agentColor(message.fromAgentId, agents)
    : BURG_LT;
  const toC = message.toAgentId
    ? agentColor(message.toAgentId, agents)
    : BURG_LT;
  const dot = large ? 9 : 6;
  const font = large ? 13 : 11.5;
  const line = large ? 34 : 16;

  const chip = (name: string, color: string) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: large ? 7 : 5,
        minWidth: 0,
      }}
    >
      <span
        style={{
          width: dot,
          height: dot,
          borderRadius: "50%",
          background: color,
          boxShadow: `0 0 ${large ? 8 : 4}px ${color}66`,
          flexShrink: 0,
        }}
      />
      <span
        style={{
          fontSize: font,
          fontWeight: 600,
          color: textColor,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {name}
      </span>
    </span>
  );

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: large ? 10 : 7,
        minWidth: 0,
        maxWidth: "100%",
      }}
    >
      {chip(message.fromAgentName, fromC)}
      <span
        style={{ display: "inline-flex", alignItems: "center", flexShrink: 0 }}
      >
        <span
          style={{
            width: line,
            height: large ? 2 : 1.5,
            background: `linear-gradient(90deg, ${fromC}, ${toC})`,
            borderRadius: 1,
          }}
        />
        <span
          style={{
            width: 0,
            height: 0,
            borderTop: `${large ? 4 : 3}px solid transparent`,
            borderBottom: `${large ? 4 : 3}px solid transparent`,
            borderLeft: `${large ? 6 : 4.5}px solid ${toC}`,
          }}
        />
      </span>
      {chip(message.toAgentName, toC)}
    </span>
  );
}

function TypeTag({ type, large }: { type: string; large?: boolean }) {
  const c = typeColor(type);
  return (
    <span
      style={{
        fontFamily: MONO,
        fontSize: large ? 10 : 9,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: c,
        background: `${c}22`,
        border: `1px solid ${c}3d`,
        borderRadius: 100,
        padding: large ? "3px 10px" : "2px 8px",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
        maxWidth: "100%",
      }}
    >
      {type}
    </span>
  );
}

/** Icon button with the house hover treatment. */
function IconBtn({
  icon,
  label,
  onClick,
  spinning,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  spinning?: boolean;
}) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [hov, setHov] = useState(false);
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="hist-focus"
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 30,
        height: 30,
        borderRadius: 8,
        border: `1px solid ${hov ? t.borderHi : "transparent"}`,
        background: hov ? t.hover : "transparent",
        color: hov ? t.text : t.textSub,
        cursor: "pointer",
        transition: "background 0.15s, color 0.15s, border-color 0.15s",
      }}
    >
      <span
        style={
          spinning
            ? { animation: "histSpin 0.9s linear infinite", display: "flex" }
            : { display: "flex" }
        }
      >
        <LIcon name={icon} size={15} color="currentColor" />
      </span>
    </button>
  );
}

interface MessageGroup {
  key: string;
  trialDescription: string;
  roundIndex: number;
  phase: string;
  items: { message: HistoryMessage; flatIndex: number }[];
}

export function HistoryPage({ onBack }: HistoryPageProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const [trials, setTrials] = useState<HistoryTrial[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [trialId, setTrialId] = useState(ALL);
  const [agentId, setAgentId] = useState(ALL);
  const [typeFilter, setTypeFilter] = useState(ALL);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<HistoryMessage | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [narrow, setNarrow] = useState(false);
  const [rawView, setRawView] = useState(false);
  const [copied, setCopied] = useState(false);

  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const measure = () => setNarrow(window.innerWidth < 880);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchHistoryTrials(),
      fetchAgents(),
      fetchHistoryMessages({
        trialId: trialId === ALL ? undefined : trialId,
        agentId: agentId === ALL ? undefined : agentId,
      }),
    ])
      .then(([trialRows, agentRows, messageRows]) => {
        if (cancelled) return;
        setTrials(trialRows);
        setAgents(agentRows);
        setMessages(messageRows);
        // Drop a type filter that no longer exists in the new scope.
        const types = new Set(messageRows.map((m) => m.messageType));
        setTypeFilter((prev) =>
          prev !== ALL && !types.has(prev) ? ALL : prev,
        );
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load history");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, trialId, reloadKey]);

  const selectTrial = useCallback(
    (id: string) => {
      if (id === trialId) return;
      setLoading(true);
      setTrialId(id);
    },
    [trialId],
  );

  const selectAgent = useCallback(
    (id: string) => {
      if (id === agentId) return;
      setLoading(true);
      setAgentId(id);
    },
    [agentId],
  );

  const refresh = useCallback(() => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  }, []);

  // Message types come from the un-type-filtered set so the list never
  // collapses to the single selected type.
  const messageTypes = useMemo(
    () => Array.from(new Set(messages.map((m) => m.messageType))).sort(),
    [messages],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return messages.filter((m) => {
      if (typeFilter !== ALL && m.messageType !== typeFilter) return false;
      if (!q) return true;
      return (
        (m.message ?? "").toLowerCase().includes(q) ||
        m.fromAgentName.toLowerCase().includes(q) ||
        m.toAgentName.toLowerCase().includes(q) ||
        m.messageType.toLowerCase().includes(q) ||
        m.phase.toLowerCase().includes(q)
      );
    });
  }, [messages, typeFilter, query]);

  const groups = useMemo(() => {
    const out: MessageGroup[] = [];
    let current: MessageGroup | null = null;
    filtered.forEach((message, flatIndex) => {
      const key = `${message.trialId}|${message.roundIndex}|${message.phase}`;
      if (!current || current.key !== key) {
        current = {
          key: `${key}|${flatIndex}`,
          trialDescription: message.trialDescription,
          roundIndex: message.roundIndex,
          phase: message.phase,
          items: [],
        };
        out.push(current);
      }
      current.items.push({ message, flatIndex });
    });
    return out;
  }, [filtered]);

  const activeIndex = useMemo(
    () => filtered.findIndex((m) => m.id === activeId),
    [filtered, activeId],
  );

  const openMessage = useCallback((message: HistoryMessage) => {
    setSelected(message);
    setActiveId(message.id);
    setRawView(false);
    setCopied(false);
  }, []);

  const step = useCallback(
    (delta: number, open: boolean) => {
      if (filtered.length === 0) return;
      const next =
        activeIndex === -1
          ? delta > 0
            ? 0
            : filtered.length - 1
          : Math.min(Math.max(activeIndex + delta, 0), filtered.length - 1);
      const message = filtered[next];
      setActiveId(message.id);
      if (open) {
        setSelected(message);
        setRawView(false);
        setCopied(false);
      }
      listRef.current
        ?.querySelector(`[data-msg-id="${message.id}"]`)
        ?.scrollIntoView({ block: "nearest" });
    },
    [filtered, activeIndex],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") {
        if (e.key === "Escape") target?.blur();
        return;
      }
      if (e.key === "Escape") {
        // An open filter dropdown consumes Escape itself.
        if (document.querySelector("[data-radix-popper-content-wrapper]"))
          return;
        if (selected) setSelected(null);
        else onBack();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        step(1, selected !== null);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        step(-1, selected !== null);
      } else if (e.key === "Enter" && activeId != null && !selected) {
        const message = filtered.find((m) => m.id === activeId);
        if (message) openMessage(message);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, onBack, step, activeId, filtered, openMessage]);

  const clientFiltersActive = typeFilter !== ALL || query.trim() !== "";
  const anyFiltersActive =
    clientFiltersActive || trialId !== ALL || agentId !== ALL;

  function clearFilters() {
    selectTrial(ALL);
    selectAgent(ALL);
    setTypeFilter(ALL);
    setQuery("");
  }

  async function copySelected() {
    if (!selected?.message) return;
    try {
      await navigator.clipboard.writeText(selected.message);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable — leave the button as-is */
    }
  }

  const rawBody = useMemo(() => {
    if (!selected?.message) return "";
    try {
      return JSON.stringify(JSON.parse(selected.message), null, 2);
    } catch {
      return selected.message;
    }
  }, [selected]);

  const hairline = dark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)";
  const railBg = dark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.015)";

  const searchStyle: React.CSSProperties = {
    flex: 1,
    minWidth: 130,
    maxWidth: 300,
    display: "flex",
    alignItems: "center",
    gap: 7,
    background: t.inputBg,
    border: `1px solid ${t.pillBorder}`,
    borderRadius: 100,
    padding: "5px 12px",
  };

  const trialSelect = (
    <Select value={trialId} onValueChange={selectTrial}>
      <SelectTrigger className="hist-focus">
        <span
          style={{
            maxWidth: 180,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            display: "block",
          }}
        >
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All trials</SelectItem>
        {trials.map((trial) => (
          <SelectItem key={trial.id} value={trial.id}>
            <span
              style={{
                maxWidth: 360,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                display: "block",
              }}
            >
              {trial.description}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Simulation history"
      style={
        {
          width: "100%",
          height: "100%",
          position: "relative",
          background: t.bg,
          color: t.text,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          "--hist-hover": t.hover,
          "--hist-active": dark
            ? "rgba(139,26,47,0.16)"
            : "rgba(139,26,47,0.08)",
        } as React.CSSProperties
      }
    >
      {/* ── Masthead ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px 12px",
          borderBottom: `1px solid ${t.border}`,
          background: t.surface,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <span
            style={{
              fontFamily: MONO,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.24em",
              color: BURG_LT,
            }}
          >
            SWARM ARCHIVE
          </span>
          <span
            style={{
              fontFamily: SERIF,
              fontStyle: "italic",
              fontWeight: 700,
              fontSize: 22,
              lineHeight: 1.15,
              letterSpacing: "-0.01em",
            }}
          >
            History
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <IconBtn
            icon="RefreshCw"
            label="Refresh"
            spinning={loading}
            onClick={refresh}
          />
          <IconBtn icon="X" label="Close history" onClick={onBack} />
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* ── Trial rail ── */}
        {!narrow && (
          <div
            style={{
              width: 248,
              flexShrink: 0,
              borderRight: `1px solid ${t.border}`,
              background: railBg,
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            <div
              style={{
                padding: "12px 16px 8px",
                display: "flex",
                alignItems: "baseline",
                justifyContent: "space-between",
              }}
            >
              <span
                style={{
                  fontFamily: MONO,
                  fontSize: 9.5,
                  fontWeight: 700,
                  letterSpacing: "0.18em",
                  color: t.textDim,
                }}
              >
                TRIALS
              </span>
              <span
                style={{ fontFamily: MONO, fontSize: 10, color: t.textDim }}
              >
                {trials.length}
              </span>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 12px" }}>
              <button
                onClick={() => selectTrial(ALL)}
                className="hist-trial hist-focus"
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "9px 10px",
                  borderRadius: 9,
                  border: "none",
                  textAlign: "left",
                  cursor: "pointer",
                  background:
                    trialId === ALL ? "var(--hist-active)" : "transparent",
                  boxShadow:
                    trialId === ALL ? `inset 2px 0 0 ${BURG_LT}` : "none",
                  color: t.text,
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                <LIcon name="Layers" size={13} color={t.textSub} />
                All trials
              </button>
              {trials.map((trial) => {
                const active = trialId === trial.id;
                return (
                  <button
                    key={trial.id}
                    onClick={() => selectTrial(trial.id)}
                    className="hist-trial hist-focus"
                    style={{
                      width: "100%",
                      display: "flex",
                      flexDirection: "column",
                      gap: 5,
                      padding: "9px 10px",
                      marginTop: 2,
                      borderRadius: 9,
                      border: "none",
                      textAlign: "left",
                      cursor: "pointer",
                      background: active ? "var(--hist-active)" : "transparent",
                      boxShadow: active ? `inset 2px 0 0 ${BURG_LT}` : "none",
                    }}
                  >
                    <span
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: 7,
                      }}
                    >
                      <span
                        title={trial.status}
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          background: statusColor(trial.status),
                          marginTop: 5,
                          flexShrink: 0,
                        }}
                      />
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 600,
                          color: t.text,
                          lineHeight: 1.4,
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                        }}
                      >
                        {trial.description}
                      </span>
                    </span>
                    <span
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        paddingLeft: 13,
                      }}
                    >
                      {trial.mode && (
                        <span
                          style={{
                            fontFamily: MONO,
                            fontSize: 8.5,
                            fontWeight: 700,
                            letterSpacing: "0.06em",
                            textTransform: "uppercase",
                            color: t.textSub,
                            background: t.hover,
                            borderRadius: 100,
                            padding: "1.5px 7px",
                            maxWidth: 110,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {trial.mode}
                        </span>
                      )}
                      <span
                        style={{
                          fontFamily: MONO,
                          fontSize: 9.5,
                          color: t.textDim,
                        }}
                      >
                        {fmtDay(trial.createdAt)} · {fmtClock(trial.createdAt)}
                      </span>
                    </span>
                  </button>
                );
              })}
              {!loading && trials.length === 0 && (
                <div
                  style={{
                    padding: "18px 10px",
                    fontSize: 11.5,
                    lineHeight: 1.6,
                    color: t.textDim,
                  }}
                >
                  No trials recorded yet.
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Transcript column ── */}
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            minHeight: 0,
          }}
        >
          {/* Filter row */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "10px 16px",
              borderBottom: `1px solid ${t.border}`,
              flexWrap: "wrap",
            }}
          >
            {narrow && trialSelect}
            <Select value={agentId} onValueChange={selectAgent}>
              <SelectTrigger className="hist-focus">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All agents</SelectItem>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 7,
                      }}
                    >
                      <span
                        style={{
                          width: 7,
                          height: 7,
                          borderRadius: "50%",
                          background: agentColor(agent.id, agents),
                        }}
                      />
                      {agent.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={typeFilter} onValueChange={setTypeFilter}>
              <SelectTrigger
                className="hist-focus"
                disabled={messageTypes.length === 0}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All types</SelectItem>
                {messageTypes.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <label style={searchStyle}>
              <LIcon name="Search" size={12} color={t.textDim} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search messages"
                aria-label="Search messages"
                style={{
                  flex: 1,
                  minWidth: 0,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: t.text,
                  fontSize: 12,
                  fontFamily: "inherit",
                }}
              />
              {query && (
                <button
                  onClick={() => setQuery("")}
                  aria-label="Clear search"
                  style={{
                    display: "flex",
                    background: "transparent",
                    border: "none",
                    color: t.textDim,
                    cursor: "pointer",
                    padding: 0,
                  }}
                >
                  <LIcon name="X" size={11} color="currentColor" />
                </button>
              )}
            </label>
            <span
              style={{
                marginLeft: "auto",
                fontFamily: MONO,
                fontSize: 10.5,
                color: t.textDim,
                whiteSpace: "nowrap",
              }}
            >
              {loading
                ? "loading…"
                : clientFiltersActive
                  ? `${filtered.length} / ${messages.length} messages`
                  : `${filtered.length} message${
                      filtered.length === 1 ? "" : "s"
                    }`}
            </span>
          </div>

          {error && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "9px 16px",
                background: dark
                  ? "rgba(139,26,47,0.18)"
                  : "rgba(139,26,47,0.08)",
                borderBottom: `1px solid rgba(139,26,47,0.3)`,
                fontSize: 12,
                color: t.text,
              }}
            >
              <LIcon name="TriangleAlert" size={14} color={BURG_LT} />
              <span style={{ flex: 1 }}>{error}</span>
              <button
                onClick={refresh}
                className="hist-focus"
                style={{
                  background: "transparent",
                  border: `1px solid rgba(139,26,47,0.4)`,
                  borderRadius: 100,
                  color: t.text,
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "3px 12px",
                }}
              >
                Retry
              </button>
            </div>
          )}

          {/* Transcript */}
          <div
            ref={listRef}
            style={{ flex: 1, overflowY: "auto", minHeight: 0 }}
          >
            {loading ? (
              <div style={{ padding: "14px 16px" }}>
                {Array.from({ length: 9 }).map((_, i) => (
                  <div
                    key={i}
                    style={{
                      height: 15,
                      borderRadius: 6,
                      marginBottom: 17,
                      width: `${88 - (i % 4) * 14}%`,
                      background: `linear-gradient(90deg, ${t.hover} 25%, ${t.borderHi} 50%, ${t.hover} 75%)`,
                      backgroundSize: "600px 100%",
                      animation: "shimmer 1.4s linear infinite",
                    }}
                  />
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <div
                style={{
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 10,
                  padding: 24,
                  textAlign: "center",
                }}
              >
                <LIcon
                  name={anyFiltersActive ? "SearchX" : "Archive"}
                  size={26}
                  color={t.textDim}
                  sw={1.4}
                />
                <div style={{ fontSize: 13.5, fontWeight: 700 }}>
                  {anyFiltersActive
                    ? "No messages match"
                    : "No messages archived yet"}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: t.textSub,
                    maxWidth: 320,
                    lineHeight: 1.6,
                  }}
                >
                  {anyFiltersActive
                    ? "Try different filters or clear them to see the full transcript."
                    : "Run a simulation and every message the swarm exchanges is archived here."}
                </div>
                {anyFiltersActive && (
                  <button
                    onClick={clearFilters}
                    className="hist-focus"
                    style={{
                      marginTop: 4,
                      background: t.hover,
                      border: `1px solid ${t.border}`,
                      borderRadius: 100,
                      color: t.text,
                      cursor: "pointer",
                      fontSize: 12,
                      fontWeight: 700,
                      padding: "6px 16px",
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            ) : (
              groups.map((group) => (
                <div key={group.key}>
                  <div
                    style={{
                      position: "sticky",
                      top: 0,
                      zIndex: 2,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "7px 16px",
                      background: t.bg,
                      borderBottom: `1px solid ${t.border}`,
                    }}
                  >
                    <span
                      style={{
                        fontFamily: MONO,
                        fontSize: 9.5,
                        fontWeight: 700,
                        letterSpacing: "0.16em",
                        color: BURG_LT,
                      }}
                    >
                      ROUND {String(group.roundIndex).padStart(2, "0")}
                    </span>
                    <span
                      style={{
                        fontFamily: MONO,
                        fontSize: 9.5,
                        fontWeight: 600,
                        letterSpacing: "0.12em",
                        textTransform: "uppercase",
                        color: t.textDim,
                      }}
                    >
                      · {group.phase}
                    </span>
                    {trialId === ALL && (
                      <span
                        style={{
                          marginLeft: "auto",
                          fontSize: 10.5,
                          color: t.textDim,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          maxWidth: "45%",
                        }}
                      >
                        {group.trialDescription}
                      </span>
                    )}
                  </div>
                  {group.items.map(({ message, flatIndex }) => (
                    <div
                      key={message.id}
                      data-msg-id={message.id}
                      className="hist-row hist-anim"
                      data-active={activeId === message.id}
                      onClick={() => openMessage(message)}
                      role="button"
                      tabIndex={-1}
                      style={{
                        display: "grid",
                        gridTemplateColumns: narrow
                          ? "minmax(150px, 220px) 1fr"
                          : "62px minmax(190px, 250px) 110px 1fr",
                        gap: 12,
                        alignItems: "center",
                        padding: "8px 16px",
                        borderBottom: `1px solid ${hairline}`,
                        cursor: "pointer",
                        animation: `histRowIn 0.28s ${
                          Math.min(flatIndex, 20) * 0.014
                        }s cubic-bezier(0.16,1,0.3,1) both`,
                      }}
                    >
                      {!narrow && (
                        <span
                          title={fmtFull(message.createdAt)}
                          style={{
                            fontFamily: MONO,
                            fontSize: 10,
                            color: t.textDim,
                          }}
                        >
                          {fmtClock(message.createdAt)}
                        </span>
                      )}
                      <RouteRibbon
                        message={message}
                        agents={agents}
                        textColor={t.text}
                      />
                      {!narrow && (
                        <span style={{ display: "flex", minWidth: 0 }}>
                          <TypeTag type={message.messageType} />
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: 12,
                          color: t.textSub,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          minWidth: 0,
                        }}
                      >
                        {message.message || (
                          <span style={{ color: t.textDim }}>—</span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* ── Detail drawer ── */}
      {selected && (
        <div
          className="hist-anim"
          style={{
            position: "absolute",
            inset: 0,
            background: "rgba(0,0,0,0.32)",
            display: "flex",
            justifyContent: "flex-end",
            zIndex: 120,
            animation: "fadeIn 0.18s ease-out",
          }}
          onClick={() => setSelected(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={`Message ${selected.id}`}
            onClick={(e) => e.stopPropagation()}
            className="hist-anim"
            style={{
              width: "min(600px, 94%)",
              height: "100%",
              background: t.surface,
              borderLeft: `1px solid ${t.borderHi}`,
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 12px 48px rgba(0,0,0,0.32)",
              animation: "logSlide 0.26s cubic-bezier(0.16,1,0.3,1)",
            }}
          >
            {/* Drawer header */}
            <div
              style={{
                padding: "16px 20px 14px",
                borderBottom: `1px solid ${t.border}`,
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <TypeTag type={selected.messageType} large />
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 10.5,
                    color: t.textDim,
                  }}
                >
                  #{selected.id}
                </span>
                <span
                  style={{
                    marginLeft: "auto",
                    display: "flex",
                    alignItems: "center",
                    gap: 2,
                  }}
                >
                  <span
                    style={{
                      fontFamily: MONO,
                      fontSize: 10.5,
                      color: t.textDim,
                      marginRight: 6,
                    }}
                  >
                    {activeIndex + 1} / {filtered.length}
                  </span>
                  <IconBtn
                    icon="ChevronUp"
                    label="Previous message"
                    onClick={() => step(-1, true)}
                  />
                  <IconBtn
                    icon="ChevronDown"
                    label="Next message"
                    onClick={() => step(1, true)}
                  />
                  <IconBtn
                    icon="X"
                    label="Close message"
                    onClick={() => setSelected(null)}
                  />
                </span>
              </div>
              <RouteRibbon
                message={selected}
                agents={agents}
                large
                textColor={t.text}
              />
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  columnGap: 18,
                  rowGap: 4,
                  fontFamily: MONO,
                  fontSize: 10.5,
                  color: t.textSub,
                }}
              >
                <span>
                  ROUND {String(selected.roundIndex).padStart(2, "0")}
                </span>
                <span style={{ textTransform: "uppercase" }}>
                  {selected.phase}
                </span>
                <span>{fmtFull(selected.createdAt)}</span>
              </div>
              <div
                style={{
                  fontSize: 11.5,
                  color: t.textDim,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={selected.trialDescription}
              >
                {selected.trialDescription}
              </div>
            </div>

            {/* Body toolbar */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 20px 0",
              }}
            >
              <div
                style={{
                  display: "flex",
                  background: t.inputBg,
                  borderRadius: 100,
                  padding: 2,
                  border: `1px solid ${t.border}`,
                }}
              >
                {(["Rendered", "Raw"] as const).map((label) => {
                  const isRaw = label === "Raw";
                  const on = rawView === isRaw;
                  return (
                    <button
                      key={label}
                      onClick={() => setRawView(isRaw)}
                      className="hist-focus"
                      style={{
                        border: "none",
                        borderRadius: 100,
                        padding: "4px 13px",
                        fontSize: 11,
                        fontWeight: 700,
                        cursor: "pointer",
                        color: on ? t.text : t.textDim,
                        background: on ? t.hover : "transparent",
                        transition: "background 0.15s, color 0.15s",
                      }}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <button
                onClick={copySelected}
                className="hist-focus"
                disabled={!selected.message}
                style={{
                  marginLeft: "auto",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  background: "transparent",
                  border: `1px solid ${t.border}`,
                  borderRadius: 100,
                  color: copied ? "#3dba8c" : t.textSub,
                  cursor: selected.message ? "pointer" : "not-allowed",
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "4px 12px",
                  opacity: selected.message ? 1 : 0.5,
                  transition: "color 0.15s",
                }}
              >
                <LIcon
                  name={copied ? "Check" : "Copy"}
                  size={12}
                  color="currentColor"
                />
                {copied ? "Copied" : "Copy"}
              </button>
            </div>

            {/* Body */}
            <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px" }}>
              {!selected.message ? (
                <div style={{ fontSize: 12.5, color: t.textDim }}>
                  No content in this message.
                </div>
              ) : rawView ? (
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontFamily: MONO,
                    fontSize: 11.5,
                    lineHeight: 1.65,
                    color: t.text,
                  }}
                >
                  {rawBody}
                </pre>
              ) : (
                <MarkdownRenderer content={selected.message} fontSize={13} />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
