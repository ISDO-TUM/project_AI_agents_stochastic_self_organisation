"use client";

import { useMemo, useState, useRef, useCallback } from "react";
import { Agent, Edge, SimStep } from "@/lib/types";
import { BURG, BURG_DIM, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon } from "@/lib/icons";

// ── Registry step detection ─────────────────────────────────────────────────
function isRegistryStep(step: SimStep): boolean {
  return (
    step.type === "tool" &&
    (step.msg.includes("Agents you can contact:") ||
      step.msg.includes("Most relevant agents:") ||
      step.msg.includes("No matching agents") ||
      step.msg.includes("Registry not available") ||
      step.msg.includes("Knowledge files:") || // registry get — success
      step.msg.includes("' not found.")) // registry get — agent not found
  );
}

const SPIRAL_COUNT = 13;
const MIN_W = 240;
const MIN_H = 180;

// ── Component ───────────────────────────────────────────────────────────────

export interface PhonebookPanelProps {
  agents: Agent[];
  steps: SimStep[];
  currentStep: number;
  dynamicEdges: Edge[];
  simMode: boolean;
  /** Current canvas zoom — used to convert screen-space drag/resize deltas to
   *  world-space deltas when the panel lives inside the .ctf world transform. */
  zoom?: number;
}

export function PhonebookPanel({
  agents,
  steps,
  currentStep,
  dynamicEdges,
  simMode,
  zoom = 1,
}: PhonebookPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  // ── drag / resize state ──────────────────────────────────────────────────
  // null = use CSS centering (initial); once the user first drags/resizes we
  // switch to explicit pixel coordinates relative to the parent.
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [size, setSize] = useState({ w: 300, h: 260 });
  const wrapRef = useRef<HTMLDivElement>(null);

  type DragState = { sx: number; sy: number; px: number; py: number };
  type ResizeState = {
    sx: number;
    sy: number;
    sw: number;
    sh: number;
    px: number;
    py: number;
    dir: string;
  };
  const dragRef = useRef<DragState | null>(null);
  const resizeRef = useRef<ResizeState | null>(null);

  /** Capture the wrapper's current top-left corner in world-space coordinates.
   *  Inside the .ctf world transform, offsetLeft/offsetTop are already world
   *  coords.  When pos===null the CSS is "left:50% + translate(-50%,-50%)",
   *  so we subtract half the panel dimensions to get the true top-left. */
  const capturePos = useCallback((): { x: number; y: number } => {
    const el = wrapRef.current;
    if (!el) return { x: 0, y: 0 };
    return { x: el.offsetLeft - size.w / 2, y: el.offsetTop - size.h / 2 };
  }, [size]);

  // Header drag ──────────────────────────────────────────────────────────────
  const onHeaderMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest("button")) return;
      e.preventDefault();
      const p = pos ?? capturePos();
      if (!pos) setPos(p);
      dragRef.current = { sx: e.clientX, sy: e.clientY, px: p.x, py: p.y };
      document.body.style.cursor = "grabbing";

      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current) return;
        setPos({
          x: dragRef.current.px + (ev.clientX - dragRef.current.sx) / zoom,
          y: dragRef.current.py + (ev.clientY - dragRef.current.sy) / zoom,
        });
      };
      const onUp = () => {
        dragRef.current = null;
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [pos, capturePos, zoom],
  );

  // Edge / corner resize ─────────────────────────────────────────────────────
  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent, dir: string) => {
      e.preventDefault();
      e.stopPropagation();
      const p = pos ?? capturePos();
      if (!pos) setPos(p);
      resizeRef.current = {
        sx: e.clientX,
        sy: e.clientY,
        sw: size.w,
        sh: size.h,
        px: p.x,
        py: p.y,
        dir,
      };
      const cursors: Record<string, string> = {
        e: "e-resize",
        s: "s-resize",
        se: "se-resize",
        sw: "sw-resize",
      };
      document.body.style.cursor = cursors[dir] ?? "nwse-resize";

      const onMove = (ev: MouseEvent) => {
        const r = resizeRef.current;
        if (!r) return;
        const dx = (ev.clientX - r.sx) / zoom;
        const dy = (ev.clientY - r.sy) / zoom;
        let nw = r.sw,
          nh = r.sh,
          nx = r.px;
        if (r.dir.includes("e")) nw = Math.max(MIN_W, r.sw + dx);
        if (r.dir.includes("s")) nh = Math.max(MIN_H, r.sh + dy);
        if (r.dir.includes("w")) {
          nw = Math.max(MIN_W, r.sw - dx);
          nx = r.px + r.sw - nw;
        }
        setSize({ w: nw, h: nh });
        setPos({ x: nx, y: r.py });
      };
      const onUp = () => {
        resizeRef.current = null;
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [pos, size, capturePos, zoom],
  );

  // ── Derived data ──────────────────────────────────────────────────────────
  const activeStep = simMode ? steps[currentStep] : null;
  const registryActive = activeStep ? isRegistryStep(activeStep) : false;
  const activeQueryAgentId = registryActive ? activeStep?.fromId : null;

  const contactedIds = useMemo(
    () => new Set(dynamicEdges.flatMap((e) => [e.from, e.to])),
    [dynamicEdges],
  );

  const connectionsByRound = useMemo(() => {
    const byRound = new Map<number, { from: string; to: string }[]>();
    if (!simMode) return byRound;
    for (let i = 0; i <= currentStep && i < steps.length; i++) {
      const s = steps[i];
      if (!s.dynamic || s.type !== "agent-to-agent" || !s.fromId || !s.toId)
        continue;
      const round = s.roundIndex ?? 1;
      if (!byRound.has(round)) byRound.set(round, []);
      const arr = byRound.get(round)!;
      const key = `${s.fromId}->${s.toId}`;
      if (!arr.some((c) => `${c.from}->${c.to}` === key))
        arr.push({ from: s.label, to: s.target ?? s.toId });
    }
    return byRound;
  }, [steps, currentStep, simMode]);

  const recentQueries = useMemo(() => {
    if (!simMode) return [];
    return steps
      .slice(0, currentStep + 1)
      .filter(isRegistryStep)
      .slice(-4);
  }, [steps, currentStep, simMode]);

  // ── Helpers ───────────────────────────────────────────────────────────────
  const sectionLabel = (text: string) => (
    <div
      style={{
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: 1.1,
        textTransform: "uppercase",
        color: t.textDim,
        fontFamily: "'JetBrains Mono', monospace",
        marginBottom: 8,
        marginTop: 4,
      }}
    >
      {text}
    </div>
  );

  const resizeHandle = (dir: string, style: React.CSSProperties) => (
    <div
      style={{ position: "absolute", zIndex: 10, ...style }}
      onMouseDown={(e) => onResizeMouseDown(e, dir)}
    />
  );

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <>
      <style>{`
        @keyframes pb-pulse {
          0%,100% { box-shadow: 0 0 0 1px ${BURG_GLOW}, 0 12px 40px rgba(0,0,0,0.55); }
          50%      { box-shadow: 0 0 0 2px ${BURG}, 0 12px 48px rgba(139,26,47,0.35), 0 0 28px ${BURG_GLOW}; }
        }
      `}</style>

      {/* Outer wrapper: owns position, size, and resize handles ──────────── */}
      <div
        ref={wrapRef}
        style={{
          position: "absolute",
          zIndex: 200,
          width: size.w,
          height: size.h,
          ...(pos === null
            ? { top: "50%", left: "50%", transform: "translate(-50%, -50%)" }
            : { top: pos.y, left: pos.x, transform: "none" }),
        }}
      >
        {/* Inner panel: visual chrome + content (overflow hidden for radius) */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            background: dark ? "rgba(8,6,18,0.97)" : "rgba(255,254,250,0.98)",
            backdropFilter: "blur(28px)",
            WebkitBackdropFilter: "blur(28px)",
            border: `1px solid ${registryActive ? BURG : t.borderHi}`,
            borderRadius: 16,
            overflow: "hidden",
            animation: registryActive
              ? "pb-pulse 1.2s ease-in-out infinite"
              : "none",
            boxShadow: dark
              ? "0 0 0 1px rgba(139,26,47,0.18), 0 12px 40px rgba(0,0,0,0.55)"
              : "0 0 0 1px rgba(139,26,47,0.08), 0 8px 28px rgba(0,0,0,0.11)",
            transition: "border-color 0.3s",
          }}
        >
          {/* Spiral binding strip */}
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: 22,
              background: dark
                ? "rgba(139,26,47,0.12)"
                : "rgba(139,26,47,0.07)",
              borderRight: `1px solid ${
                dark ? "rgba(139,26,47,0.22)" : "rgba(139,26,47,0.14)"
              }`,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "space-around",
              paddingTop: 10,
              paddingBottom: 10,
              zIndex: 1,
              pointerEvents: "none",
            }}
          >
            {Array.from({ length: SPIRAL_COUNT }).map((_, i) => (
              <div
                key={i}
                style={{
                  position: "relative",
                  width: 13,
                  height: 13,
                  flexShrink: 0,
                }}
              >
                {/* Back of coil ring — faint full circle */}
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    borderRadius: "50%",
                    border: `1.5px solid ${
                      dark ? "rgba(139,26,47,0.28)" : "rgba(139,26,47,0.20)"
                    }`,
                  }}
                />
                {/* Front arc — bright C-shape, open toward content */}
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    borderRadius: "50%",
                    borderTop: `2px solid ${
                      dark ? "rgba(139,26,47,0.70)" : "rgba(139,26,47,0.52)"
                    }`,
                    borderLeft: `2px solid ${
                      dark ? "rgba(139,26,47,0.70)" : "rgba(139,26,47,0.52)"
                    }`,
                    borderBottom: `2px solid ${
                      dark ? "rgba(139,26,47,0.70)" : "rgba(139,26,47,0.52)"
                    }`,
                    borderRight: "2px solid transparent",
                  }}
                />
              </div>
            ))}
          </div>

          {/* Content area (inset past binding) */}
          <div
            style={{
              marginLeft: 22,
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
              flex: 1,
            }}
          >
            {/* Header — drag handle */}
            <div
              onMouseDown={onHeaderMouseDown}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                padding: "11px 14px 10px",
                borderBottom: `1px solid ${t.border}`,
                flexShrink: 0,
                cursor: "grab",
                userSelect: "none",
              }}
            >
              <LIcon name="BookOpen" size={13} color={BURG} />
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: 0.2,
                  color: t.text,
                }}
              >
                Phone Book
              </span>
              {registryActive && (
                <span
                  style={{
                    fontSize: 8,
                    fontWeight: 700,
                    letterSpacing: 0.6,
                    textTransform: "uppercase",
                    fontFamily: "'JetBrains Mono', monospace",
                    color: BURG,
                    background: BURG_DIM,
                    borderRadius: 4,
                    padding: "1px 6px",
                    marginLeft: 2,
                  }}
                >
                  querying
                </span>
              )}
              <div style={{ marginLeft: "auto", opacity: 0.35 }}>
                <LIcon name="GripVertical" size={12} color={t.textSub} />
              </div>
            </div>

            {/* Scrollable body */}
            <div
              className="pscroll"
              style={{ flex: 1, overflowY: "auto", padding: "10px 14px 14px" }}
            >
              {/* Roster */}
              {sectionLabel("Roster")}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  marginBottom: 14,
                }}
              >
                {agents.length === 0 && (
                  <div
                    style={{
                      fontSize: 11,
                      color: t.textDim,
                      fontStyle: "italic",
                      padding: "8px 0",
                    }}
                  >
                    No agents configured.
                  </div>
                )}
                {agents.map((agent) => {
                  const isQuerying = agent.id === activeQueryAgentId;
                  const wasContacted = contactedIds.has(agent.id);
                  return (
                    <div
                      key={agent.id}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: 8,
                        padding: "7px 10px",
                        borderRadius: 10,
                        background: isQuerying
                          ? dark
                            ? "rgba(139,26,47,0.18)"
                            : "rgba(139,26,47,0.08)"
                          : wasContacted
                            ? dark
                              ? "rgba(255,255,255,0.04)"
                              : "rgba(139,26,47,0.03)"
                            : dark
                              ? "rgba(255,255,255,0.025)"
                              : "rgba(0,0,0,0.025)",
                        border: `1px solid ${
                          isQuerying ? "rgba(139,26,47,0.40)" : t.border
                        }`,
                        transition: "all 0.25s",
                      }}
                    >
                      <div
                        style={{
                          width: 26,
                          height: 26,
                          borderRadius: "50%",
                          background: isQuerying
                            ? BURG
                            : dark
                              ? "rgba(139,26,47,0.22)"
                              : "rgba(139,26,47,0.10)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                          transition: "background 0.25s",
                        }}
                      >
                        <LIcon
                          name="Bot"
                          size={13}
                          color={isQuerying ? "#fff" : BURG}
                        />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 5,
                            marginBottom: 2,
                            flexWrap: "wrap",
                          }}
                        >
                          <span
                            style={{
                              fontSize: 11.5,
                              fontWeight: 700,
                              color: isQuerying ? BURG : t.text,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              maxWidth: "100%",
                              transition: "color 0.25s",
                            }}
                          >
                            {agent.name}
                          </span>
                          {wasContacted && (
                            <LIcon
                              name="Phone"
                              size={9}
                              color={dark ? "#C98A35" : "#9A5B05"}
                            />
                          )}
                          {isQuerying && (
                            <span
                              style={{
                                fontSize: 8,
                                fontWeight: 700,
                                color: BURG,
                                fontFamily: "'JetBrains Mono', monospace",
                                letterSpacing: 0.5,
                                textTransform: "uppercase",
                              }}
                            >
                              querying
                            </span>
                          )}
                        </div>
                        {agent.description && (
                          <div
                            style={{
                              fontSize: 10,
                              color: t.textDim,
                              lineHeight: 1.4,
                              overflow: "hidden",
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                            }}
                          >
                            {agent.description}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Connections formed per round */}
              {connectionsByRound.size > 0 && (
                <>
                  {sectionLabel("Connections Declared")}
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                      marginBottom: 14,
                    }}
                  >
                    {Array.from(connectionsByRound.entries())
                      .sort(([a], [b]) => a - b)
                      .map(([round, conns]) => (
                        <div key={round}>
                          <div
                            style={{
                              fontSize: 9,
                              color: t.textSub,
                              fontFamily: "'JetBrains Mono', monospace",
                              marginBottom: 5,
                            }}
                          >
                            Round {round}
                          </div>
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: 3,
                            }}
                          >
                            {conns.map((c, i) => (
                              <div
                                key={i}
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 5,
                                  fontSize: 10.5,
                                  color: t.text,
                                  padding: "2px 0",
                                }}
                              >
                                <LIcon
                                  name="Phone"
                                  size={9}
                                  color={dark ? "#C98A35" : "#9A5B05"}
                                />
                                <span style={{ fontWeight: 600 }}>
                                  {c.from}
                                </span>
                                <span
                                  style={{ color: t.textDim, fontSize: 10 }}
                                >
                                  →
                                </span>
                                <span style={{ fontWeight: 600 }}>{c.to}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                  </div>
                </>
              )}

              {/* Recent registry queries — 2-row compact card per event */}
              {recentQueries.length > 0 && (
                <>
                  {sectionLabel("Registry Activity")}
                  <div
                    style={{ display: "flex", flexDirection: "column", gap: 4 }}
                  >
                    {recentQueries.map((step) => {
                      const noMatch =
                        step.msg.includes("No matching agents") ||
                        step.msg.includes("' not found.");
                      const unavail = step.msg.includes(
                        "Registry not available",
                      );
                      const outcome = unavail
                        ? "unavail"
                        : noMatch
                          ? "no match"
                          : "found";
                      const outColor = noMatch || unavail ? t.textDim : BURG;

                      // Parse action type from the msg header produced by _format_tool_message
                      const isGet = step.msg.includes("**action:** `get`");
                      const isSearch = step.msg.includes(
                        "**action:** `search`",
                      );

                      let actionLabel: string;
                      if (isGet) {
                        // Result section: "```\nUUID · name\n..." (code-fenced when multi-line)
                        const resultRaw =
                          step.msg.split("**Result:**\n")[1] ?? "";
                        const resultClean = resultRaw.startsWith("```\n")
                          ? resultRaw.slice(4)
                          : resultRaw;
                        const firstLine = resultClean.split("\n")[0];
                        const targetName = firstLine.includes("·")
                          ? firstLine.split("·")[1]?.trim()
                          : null;
                        actionLabel = targetName
                          ? `get · ${targetName}`
                          : "get";
                      } else if (isSearch) {
                        const qm = step.msg.match(/\*\*query:\*\* `([^`]+)`/);
                        actionLabel = qm?.[1]
                          ? `search · "${qm[1]}"`
                          : "search";
                      } else {
                        actionLabel = "list";
                      }

                      return (
                        <div
                          key={step.id}
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 2,
                            padding: "5px 8px",
                            borderRadius: 7,
                            background: dark
                              ? "rgba(255,255,255,0.026)"
                              : "rgba(0,0,0,0.022)",
                            border: `1px solid ${t.border}`,
                          }}
                        >
                          {/* Row 1: agent name · outcome badge · timestamp */}
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            <LIcon name="Search" size={9} color={outColor} />
                            <span
                              style={{
                                fontSize: 10.5,
                                fontWeight: 600,
                                color: t.text,
                                flex: 1,
                                minWidth: 0,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {step.label}
                            </span>
                            <span
                              style={{
                                fontSize: 8.5,
                                fontWeight: 700,
                                color: outColor,
                                fontFamily: "'JetBrains Mono', monospace",
                                letterSpacing: 0.4,
                                textTransform: "uppercase",
                                flexShrink: 0,
                              }}
                            >
                              {outcome}
                            </span>
                            <span
                              style={{
                                fontSize: 8.5,
                                color: t.textDim,
                                fontFamily: "'JetBrains Mono', monospace",
                                flexShrink: 0,
                              }}
                            >
                              {step.ts}
                            </span>
                          </div>
                          {/* Row 2: action sub-label (list / get · target / search · "query") */}
                          <div
                            style={{
                              fontSize: 9,
                              color: t.textSub,
                              fontFamily: "'JetBrains Mono', monospace",
                              paddingLeft: 15,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {actionLabel}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Resize handles — outside overflow:hidden so fully hittable ──── */}
        {/* Right edge */}
        {resizeHandle("e", {
          right: -4,
          top: 16,
          bottom: 16,
          width: 8,
          cursor: "e-resize",
        })}
        {/* Bottom edge */}
        {resizeHandle("s", {
          bottom: -4,
          left: 16,
          right: 16,
          height: 8,
          cursor: "s-resize",
        })}
        {/* Bottom-right corner */}
        {resizeHandle("se", {
          right: -4,
          bottom: -4,
          width: 20,
          height: 20,
          cursor: "se-resize",
        })}
        {/* Bottom-left corner */}
        {resizeHandle("sw", {
          left: -4,
          bottom: -4,
          width: 20,
          height: 20,
          cursor: "sw-resize",
        })}
      </div>
    </>
  );
}
