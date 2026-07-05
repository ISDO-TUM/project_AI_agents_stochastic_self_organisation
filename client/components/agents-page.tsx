"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { fetchAgents, fetchAgentFiles, deleteAgentApi } from "@/lib/api";
import { Agent, KnowledgeFile } from "@/lib/types";
import { BURG, BURG_DIM, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { agentColor } from "@/lib/agent-color";
import { LIcon } from "@/lib/icons";
import { FBtn, FLabel, PanelShell } from "@/components/panels/panel-primitives";
import {
  EmptyState,
  ENTRANCE,
  cardSurface,
  labelStyle,
  MONO,
} from "@/components/statistics/primitives";

function truncateContent(text: string, max = 70): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}…` : clean;
}

function Sep({ t }: { t: ReturnType<typeof getTheme> }) {
  return (
    <div
      style={{ width: 1, height: 18, background: t.border, margin: "0 3px" }}
    />
  );
}

function HeaderLink({
  href,
  icon,
  children,
  t,
}: {
  href: string;
  icon: string;
  children: React.ReactNode;
  t: ReturnType<typeof getTheme>;
}) {
  const [hov, setHov] = useState(false);
  return (
    <Link
      href={href}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: hov ? t.hover : "transparent",
        borderRadius: 8,
        color: hov ? t.text : t.textSub,
        fontSize: 12,
        fontWeight: 600,
        padding: "6px 11px",
        display: "flex",
        alignItems: "center",
        gap: 6,
        transition: "all 0.15s",
        whiteSpace: "nowrap",
        textDecoration: "none",
      }}
    >
      <LIcon name={icon} size={14} color="currentColor" />
      {children}
    </Link>
  );
}

function PillButton({
  icon,
  title,
  onClick,
  t,
}: {
  icon: string;
  title: string;
  onClick: () => void;
  t: ReturnType<typeof getTheme>;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: "none",
        border: "none",
        cursor: "pointer",
        color: t.textSub,
        padding: "5px 7px",
        borderRadius: 8,
        display: "flex",
        alignItems: "center",
        transition: "all 0.15s",
      }}
      onMouseEnter={(e) =>
        ((e.currentTarget as HTMLButtonElement).style.color = t.text)
      }
      onMouseLeave={(e) =>
        ((e.currentTarget as HTMLButtonElement).style.color = t.textSub)
      }
    >
      <LIcon name={icon} size={15} color="currentColor" />
    </button>
  );
}

export function AgentsPage() {
  const { dark, toggle } = useTheme();
  const t = getTheme(dark);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Agent | null>(null);
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAgents()
      .then((rows) => {
        if (cancelled) return;
        setAgents(rows);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load agents");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setDeleteConfirm(false);
    setDeleteError(null);
    setFilesLoading(true);
    setFilesError(null);
    setFiles([]);
    fetchAgentFiles(selected.id)
      .then((rows) => {
        if (cancelled) return;
        setFiles(rows);
        setFilesLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFilesError(
          err instanceof Error ? err.message : "Failed to load files",
        );
        setFilesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const handleDelete = async () => {
    if (!selected || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteAgentApi(selected.id);
      setAgents((prev) => prev.filter((a) => a.id !== selected.id));
      setSelected(null);
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete agent",
      );
    } finally {
      setDeleting(false);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((a) =>
      [a.name, a.description, a.provider, a.model, ...a.tools]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [agents, query]);

  const readOnlyField: React.CSSProperties = {
    width: "100%",
    background: t.inputBg,
    border: `1.5px solid ${t.border}`,
    borderRadius: 10,
    color: t.text,
    fontSize: 13,
    padding: "10px 13px",
    lineHeight: 1.55,
    boxSizing: "border-box",
  };

  return (
    <main
      style={{
        background: dark
          ? "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.07) 0%, transparent 70%), #060608"
          : "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.04) 0%, transparent 70%), #f0eef8",
        color: t.text,
        height: "100vh",
        overflow: "hidden",
      }}
    >
      <div
        className="pscroll"
        style={{
          height: "100%",
          overflowY: "auto",
          overscrollBehavior: "contain",
          scrollbarGutter: "stable",
          padding: "0 24px 56px",
        }}
      >
        {/* floating pill header, matching the canvas toolbar */}
        <div
          style={{
            position: "sticky",
            top: 0,
            zIndex: 100,
            display: "flex",
            justifyContent: "center",
            padding: "16px 0 14px",
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "8px 14px",
              background: t.pill,
              backdropFilter: "blur(28px)",
              WebkitBackdropFilter: "blur(28px)",
              border: `1px solid ${t.pillBorder}`,
              borderRadius: 100,
              pointerEvents: "all",
              flexWrap: "wrap",
              justifyContent: "center",
              animation: `${
                dark ? "pillPulse" : "pillPulseLight"
              } 4s ease-in-out infinite`,
              boxShadow: dark
                ? "0 0 0 1px rgba(139,26,47,0.14), 0 4px 20px rgba(139,26,47,0.12), 0 8px 36px rgba(0,0,0,0.35)"
                : "0 0 0 1px rgba(139,26,47,0.10), 0 4px 18px rgba(139,26,47,0.10), 0 6px 24px rgba(0,0,0,0.07)",
            }}
          >
            <HeaderLink href="/" icon="ArrowLeft" t={t}>
              Canvas
            </HeaderLink>

            <Sep t={t} />

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "0 8px",
              }}
            >
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 8,
                  background: BURG_DIM,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <LIcon name="Bot" size={14} color={BURG} />
              </div>
              <span
                style={{
                  fontWeight: 700,
                  fontSize: 13.5,
                  color: t.text,
                  letterSpacing: 0.4,
                }}
              >
                Agents
              </span>
            </div>

            <Sep t={t} />

            <PillButton
              icon="RefreshCw"
              title="Refresh"
              onClick={() => {
                setLoading(true);
                setReloadKey((k) => k + 1);
              }}
              t={t}
            />
            <PillButton
              icon={dark ? "Sun" : "Moon"}
              title="Toggle theme"
              onClick={toggle}
              t={t}
            />
          </div>
        </div>

        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          {/* search + count row */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              margin: "10px 0 18px",
              flexWrap: "wrap",
            }}
          >
            <div style={{ position: "relative", flex: 1, minWidth: 240 }}>
              <span
                style={{
                  position: "absolute",
                  left: 13,
                  top: "50%",
                  transform: "translateY(-50%)",
                  display: "flex",
                  pointerEvents: "none",
                }}
              >
                <LIcon name="Search" size={14} color={t.textDim} />
              </span>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search agents by name, model, or tool…"
                style={{
                  width: "100%",
                  background: t.inputBg,
                  border: `1.5px solid ${t.border}`,
                  borderRadius: 10,
                  color: t.text,
                  fontSize: 13,
                  padding: "10px 13px 10px 36px",
                  outline: "none",
                  boxSizing: "border-box",
                  transition: "border-color 0.15s, box-shadow 0.15s",
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = BURG;
                  e.target.style.boxShadow = `0 0 0 3px ${BURG_DIM}`;
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = t.border;
                  e.target.style.boxShadow = "none";
                }}
              />
            </div>
            <span style={{ ...labelStyle(dark), letterSpacing: 0.8 }}>
              {filtered.length} agent{filtered.length === 1 ? "" : "s"}
              {query.trim() ? ` of ${agents.length}` : ""}
            </span>
          </div>

          {error && (
            <div
              style={{
                ...cardSurface(dark),
                padding: "12px 18px",
                marginBottom: 14,
                color: "#e05555",
                fontSize: 12.5,
              }}
            >
              {error}
            </div>
          )}

          {loading ? (
            <div style={{ ...labelStyle(dark), padding: "8px 2px" }}>
              Loading…
            </div>
          ) : agents.length === 0 ? (
            <EmptyState
              icon="Bot"
              title="No agents yet"
              sub="Create agents on the canvas and they will show up here."
              dark={dark}
              action={
                <Link
                  href="/"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 7,
                    background: BURG,
                    color: "#fff",
                    borderRadius: 10,
                    fontSize: 13,
                    fontWeight: 600,
                    padding: "10px 18px",
                    textDecoration: "none",
                    boxShadow: "0 2px 12px rgba(139,26,47,0.22)",
                  }}
                >
                  <LIcon name="ArrowLeft" size={14} color="currentColor" />
                  Back to canvas
                </Link>
              }
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon="Search"
              title="No matching agents"
              sub={`Nothing matches “${query.trim()}”. Try a different name, model, or tool.`}
              dark={dark}
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {filtered.map((agent, i) => (
                <div
                  key={agent.id}
                  onClick={() => setSelected(agent)}
                  onMouseEnter={() => setHoveredId(agent.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  style={{
                    ...cardSurface(dark),
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 14,
                    padding: "16px 20px",
                    cursor: "pointer",
                    transition: "border-color 0.15s, transform 0.15s",
                    borderColor: hoveredId === agent.id ? t.borderHi : t.border,
                    transform:
                      hoveredId === agent.id
                        ? "translateY(-1px)"
                        : "translateY(0)",
                    animation: ENTRANCE,
                    animationDelay: `${Math.min(i * 40, 400)}ms`,
                  }}
                >
                  <div
                    style={{
                      width: 38,
                      height: 38,
                      borderRadius: 12,
                      background: `color-mix(in srgb, ${agentColor(
                        agent.id,
                        agents,
                      )} 16%, transparent)`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                      marginTop: 1,
                    }}
                  >
                    <LIcon
                      name="Bot"
                      size={18}
                      color={agentColor(agent.id, agents)}
                    />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        flexWrap: "wrap",
                      }}
                    >
                      <span style={{ fontSize: 14, fontWeight: 700 }}>
                        {agent.name}
                      </span>
                      <span
                        style={{
                          fontSize: 10,
                          background: t.pill,
                          border: `1px solid ${t.border}`,
                          borderRadius: 5,
                          padding: "2px 8px",
                          color: t.textSub,
                          fontFamily: MONO,
                        }}
                      >
                        {agent.provider} / {agent.model}
                      </span>
                    </div>
                    {agent.description && (
                      <div
                        style={{
                          marginTop: 5,
                          fontSize: 12.5,
                          color: t.textSub,
                          lineHeight: 1.55,
                        }}
                      >
                        {agent.description}
                      </div>
                    )}
                    {agent.tools.length > 0 && (
                      <div
                        style={{
                          marginTop: 9,
                          display: "flex",
                          gap: 6,
                          flexWrap: "wrap",
                        }}
                      >
                        {agent.tools.map((tool) => (
                          <span
                            key={tool}
                            style={{
                              fontSize: 10,
                              background: t.hover,
                              border: `1px solid ${t.border}`,
                              borderRadius: 20,
                              padding: "2px 9px",
                              color: t.textDim,
                              fontFamily: MONO,
                            }}
                          >
                            {tool}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <span
                    style={{
                      display: "flex",
                      alignSelf: "center",
                      color: t.textDim,
                      flexShrink: 0,
                    }}
                  >
                    <LIcon name="ChevronRight" size={15} color="currentColor" />
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selected && (
        <PanelShell
          key={selected.id}
          title={selected.name}
          icon="Bot"
          onClose={() => setSelected(null)}
        >
          {selected.description && (
            <>
              <FLabel>Description</FLabel>
              <div style={readOnlyField}>{selected.description}</div>
            </>
          )}
          <FLabel>Provider</FLabel>
          <div style={readOnlyField}>{selected.provider}</div>
          <FLabel>Model</FLabel>
          <div style={readOnlyField}>{selected.model}</div>
          {selected.systemPrompt && (
            <>
              <FLabel>System Prompt</FLabel>
              <div
                style={{
                  ...readOnlyField,
                  fontFamily: MONO,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {selected.systemPrompt}
              </div>
            </>
          )}

          <FLabel>Knowledge Files</FLabel>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 6,
              padding: "2px 0 4px",
            }}
          >
            {filesError && (
              <span
                style={{
                  fontSize: 11.5,
                  color: "#e05555",
                  padding: "4px 4px 2px",
                }}
              >
                {filesError}
              </span>
            )}
            {filesLoading && (
              <span
                style={{
                  fontSize: 11.5,
                  color: t.textDim,
                  padding: "4px 4px 2px",
                }}
              >
                Loading…
              </span>
            )}
            {!filesLoading && !filesError && files.length === 0 && (
              <span
                style={{
                  fontSize: 11.5,
                  color: t.textDim,
                  padding: "4px 4px 2px",
                }}
              >
                No knowledge files connected.
              </span>
            )}
            {files.map((file) => (
              <div
                key={file.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 10px 8px 12px",
                  borderRadius: 8,
                  border: `1.5px solid ${t.border}`,
                  background: t.inputBg,
                }}
              >
                <LIcon name="FileText" size={13} color={t.textSub} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span
                    style={{
                      display: "block",
                      fontSize: 12,
                      color: t.text,
                      fontWeight: 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {file.name}
                  </span>
                  {file.content && (
                    <span style={{ fontSize: 10.5, color: t.textSub }}>
                      {truncateContent(file.content)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {deleteError && (
            <div
              style={{
                marginTop: 14,
                fontSize: 11.5,
                color: "#e05555",
              }}
            >
              {deleteError}
            </div>
          )}

          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
              marginTop: 24,
              paddingTop: 16,
              borderTop: `1px solid ${t.border}`,
            }}
          >
            {deleteConfirm ? (
              <>
                <span
                  style={{ fontSize: 12, color: "#e05555", fontWeight: 600 }}
                >
                  Delete permanently?
                </span>
                <div style={{ display: "flex", gap: 10 }}>
                  <FBtn onClick={() => setDeleteConfirm(false)}>Cancel</FBtn>
                  <FBtn variant="danger" icon="Trash2" onClick={handleDelete}>
                    {deleting ? "Deleting…" : "Confirm"}
                  </FBtn>
                </div>
              </>
            ) : (
              <>
                <div />
                <FBtn
                  variant="danger"
                  icon="Trash2"
                  onClick={() => setDeleteConfirm(true)}
                >
                  Delete Agent
                </FBtn>
              </>
            )}
          </div>
        </PanelShell>
      )}
    </main>
  );
}
