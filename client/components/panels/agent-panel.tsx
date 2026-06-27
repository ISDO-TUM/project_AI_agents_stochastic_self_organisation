"use client";

import { useState, useMemo, useEffect } from "react";
import { Agent, Provider, Source, Edge } from "@/lib/types";
import { uuid, shortId, PROVIDERS } from "@/lib/utils";
import { fetchModels, ModelEntry } from "@/lib/api";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { useApiKeys } from "@/lib/api-keys-context";
import { LIcon } from "@/lib/icons";
import { FLabel, FInput, FSelect, FBtn, PanelShell } from "./panel-primitives";

interface AgentPanelProps {
  agent: Agent | null;
  agents: Agent[];
  sources: Source[];
  edges: Edge[];
  onSave: (agent: Agent) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  /** Opens the source edit panel for an already-connected file/dataset. */
  onEditSource?: (sourceId: string) => void;
  /** Detaches a source from this agent (removes the edge, does not delete the source). */
  onDetachSource?: (sourceId: string) => void;
  /** Opens the "new text file" panel pre-linked to this agent. */
  onAddFile?: () => void;
  /** Opens the "new dataset" panel pre-linked to this agent. */
  onAddDataset?: () => void;
  /** Live width of a currently-open source overlay panel; 0/omitted when none is open. */
  overlayWidth?: number;
}

interface AgentForm {
  name: string;
  description: string;
  provider: Provider;
  model: string;
  systemPrompt: string;
}

const defaultForm = (): AgentForm => ({
  name: "",
  description: "",
  provider: "openai",
  model: PROVIDERS["openai"].models[0].value,
  systemPrompt: "",
});

/** Two UI-level tool categories shown in the panel.
 *  "table" expands to both backend tools (table_query + table_mutate). */
const UI_TOOLS: { key: string; label: string; description: string; icon: string }[] = [
  {
    key: "files",
    label: "Text File",
    description: "Read content from attached text files.",
    icon: "FileText",
  },
  {
    key: "table",
    label: "Table",
    description: "Query and mutate rows in a connected dataset.",
    icon: "Table2",
  },
];

/** Expand a UI tool key to the actual backend tool name(s). */
const UI_TO_BACKEND: Record<string, string[]> = {
  files: ["files"],
  table: ["table_query", "table_mutate"],
};

/** All backend tool names that are governed by the UI model. */
const ALL_BACKEND_TOOLS = Object.values(UI_TO_BACKEND).flat();

/** Collapse a list of backend tool names into deduped UI tool keys. */
function backendToUiTools(backendTools: string[]): string[] {
  const keys = new Set<string>();
  for (const t of backendTools) {
    if (t === "files") keys.add("files");
    if (t === "table_query" || t === "table_mutate") keys.add("table");
  }
  return UI_TOOLS.map((u) => u.key).filter((k) => keys.has(k));
}

function truncateContent(text: string, max = 70): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}…` : clean;
}

export function AgentPanel({
  agent,
  agents,
  sources,
  edges,
  onSave,
  onDelete,
  onClose,
  onEditSource,
  onDetachSource,
  onAddFile,
  onAddDataset,
  overlayWidth,
}: AgentPanelProps) {
  const [availableModels, setAvailableModels] = useState<ModelEntry[]>([]);
  const { keys } = useApiKeys();

  useEffect(() => {
    fetchModels().then(setAvailableModels).catch(console.error);
  }, [keys]);

  const providers = useMemo(() => {
    const map: Record<
      string,
      { label: string; models: Array<{ label: string; value: string }> }
    > = {};
    for (const m of availableModels) {
      if (!map[m.provider]) {
        map[m.provider] = {
          label: m.provider.charAt(0).toUpperCase() + m.provider.slice(1),
          models: [],
        };
      }
      map[m.provider].models.push({ label: m.name, value: m.id });
    }
    return map;
  }, [availableModels]);

  const [form, setForm] = useState<AgentForm>(
    agent
      ? {
          name: agent.name,
          description: agent.description,
          provider: agent.provider,
          model: agent.model,
          systemPrompt: agent.systemPrompt,
        }
      : defaultForm(),
  );

  useEffect(() => {
    if (!availableModels.length) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm((f) => {
      const providerModels = providers[f.provider]?.models ?? [];
      const isValid = providerModels.some((m) => m.value === f.model);
      if (!isValid && providerModels.length > 0) {
        return { ...f, model: providerModels[0].value };
      }
      return f;
    });
  }, [availableModels, providers]);

  const set = <K extends keyof AgentForm>(k: K, v: AgentForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const handleProv = (v: string) => {
    const provider = v as Provider;
    const firstModel = providers[provider]?.models[0]?.value ?? "";
    setForm((f) => ({ ...f, provider, model: firstModel }));
  };

  const nameById = useMemo(
    () => new Map(agents.map((a) => [a.id, a.name])),
    [agents],
  );
  const getName = (id: string) => nameById.get(id) ?? `${shortId(id)}…`;

  const connectedSources = useMemo(() => {
    if (!agent) return [];
    const sourceIds = new Set(
      edges
        .filter((e) => e.from === agent.id || e.to === agent.id)
        .map((e) => (e.from === agent.id ? e.to : e.from)),
    );
    return sources.filter((s) => sourceIds.has(s.id));
  }, [agent, edges, sources]);

  const generalTools = useMemo(
    () => backendToUiTools(agent?.tools ?? []),
    [agent],
  );

  const [localTools, setLocalTools] = useState<string[]>(generalTools);

  const addTool = (key: string) =>
    setLocalTools((prev) => (prev.includes(key) ? prev : [...prev, key]));
  const removeTool = (key: string) =>
    setLocalTools((prev) => prev.filter((k) => k !== key));

  const availableToAdd = UI_TOOLS.filter((u) => !localTools.includes(u.key));

  const handleSave = () => {
    const position = agent?.position ?? {
      x: 220 + Math.random() * 480,
      y: 200 + Math.random() * 260,
    };
    onSave({
      ...form,
      id: agent?.id ?? uuid(),
      position,
      // Preserve any non-governed backend tools, then expand UI keys to backend names
      tools: [
        ...(agent?.tools ?? []).filter((t) => !ALL_BACKEND_TOOLS.includes(t)),
        ...localTools.flatMap((key) => UI_TO_BACKEND[key] ?? []),
      ],
      connections: agent?.connections ?? [],
    });
  };

  const [connsOpen, setConnsOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(true);

  const { dark } = useTheme();
  const t = getTheme(dark);

  const dropdownHeader = (
    label: string,
    icon: string,
    count: number,
    open: boolean,
    toggle: () => void,
  ) => (
    <button
      onClick={toggle}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        width: "100%",
        background: t.inputBg,
        border: `1.5px solid ${t.border}`,
        borderRadius: 9,
        padding: "8px 12px",
        cursor: "pointer",
        marginTop: 4,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <LIcon name={icon} size={13} color={t.textSub} />
        <span style={{ fontSize: 13, color: t.text, fontWeight: 500 }}>
          {label}
        </span>
        <span
          style={{
            fontSize: 11,
            color: t.textDim,
            background: t.border,
            borderRadius: 5,
            padding: "1px 6px",
          }}
        >
          {count}
        </span>
      </div>
      <span
        style={{
          display: "flex",
          transform: open ? "rotate(180deg)" : "rotate(0deg)",
          transition: "transform 0.15s",
        }}
      >
        <LIcon name="ChevronDown" size={14} color={t.textSub} />
      </span>
    </button>
  );

  return (
    <PanelShell
      title={agent ? "Configure Agent" : "New Agent"}
      onClose={onClose}
      icon={agent ? "Bot" : "Plus"}
      stackOffset={overlayWidth ?? 0}
    >
      <FLabel>Name</FLabel>
      <FInput
        value={form.name}
        onChange={(v) => set("name", v)}
        placeholder="Agent name"
      />
      <FLabel>Description</FLabel>
      <FInput
        value={form.description}
        onChange={(v) => set("description", v)}
        placeholder="What does this agent do?"
      />
      <FLabel>Provider</FLabel>
      <FSelect
        value={form.provider}
        onChange={handleProv}
        options={Object.entries(providers).map(([value, { label }]) => ({
          value,
          label,
        }))}
      />
      <FLabel>Model</FLabel>
      <FSelect
        value={form.model}
        onChange={(v) => set("model", v)}
        options={(providers[form.provider]?.models ?? []).map((m) => ({
          value: m.value,
          label: m.label,
        }))}
      />
      <FLabel>System Prompt</FLabel>
      <FInput
        value={form.systemPrompt}
        onChange={(v) => set("systemPrompt", v)}
        placeholder="You are a helpful assistant…"
        multiline
        rows={5}
      />

      {/* ── Tools — connected files/datasets + capability toggles, merged ── */}
      <>
        {dropdownHeader(
          "Tools",
          "Wrench",
          connectedSources.length + localTools.length,
          toolsOpen,
          () => setToolsOpen((o) => !o),
        )}
        {toolsOpen && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 6,
              marginTop: 6,
              padding: "2px 0 4px",
            }}
          >
            {connectedSources.length === 0 && localTools.length === 0 && (
              <span
                style={{
                  fontSize: 11.5,
                  color: t.textDim,
                  padding: "4px 4px 2px",
                }}
              >
                No tools assigned yet.
              </span>
            )}

            {connectedSources.map((src) => (
              <div
                key={src.id}
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
                <LIcon
                  name={src.type === "dataset" ? "Table2" : "FileText"}
                  size={13}
                  color={t.textSub}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 12, color: t.text, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {src.name}
                    </span>
                    <span style={{ fontSize: 9.5, color: t.textDim, textTransform: "uppercase", flexShrink: 0 }}>
                      {src.type}
                    </span>
                  </div>
                  {src.content && (
                    <span style={{ fontSize: 10.5, color: t.textSub }}>
                      {truncateContent(src.content)}
                    </span>
                  )}
                </div>
                {/* Edit button */}
                {onEditSource && (
                  <button
                    onClick={() => onEditSource(src.id)}
                    title="Edit file"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: "3px 5px",
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                      color: t.textDim,
                      flexShrink: 0,
                      transition: "color 0.15s, background 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = t.text;
                      (e.currentTarget as HTMLButtonElement).style.background = t.hover;
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = t.textDim;
                      (e.currentTarget as HTMLButtonElement).style.background = "none";
                    }}
                  >
                    <LIcon name="Pencil" size={12} color="currentColor" />
                  </button>
                )}
                {/* Detach button */}
                {onDetachSource && (
                  <button
                    onClick={() => onDetachSource(src.id)}
                    title="Detach from agent"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: "3px 5px",
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                      color: t.textDim,
                      flexShrink: 0,
                      transition: "color 0.15s, background 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = "#e05555";
                      (e.currentTarget as HTMLButtonElement).style.background = "rgba(224,85,85,0.1)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = t.textDim;
                      (e.currentTarget as HTMLButtonElement).style.background = "none";
                    }}
                  >
                    <LIcon name="Unlink" size={12} color="currentColor" />
                  </button>
                )}
              </div>
            ))}

            {localTools.map((key) => {
              const uiTool = UI_TOOLS.find((u) => u.key === key);
              if (!uiTool) return null;
              return (
              <div
                key={key}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "9px 12px",
                  borderRadius: 8,
                  border: `1.5px solid ${t.border}`,
                  background: t.inputBg,
                  gap: 10,
                }}
              >
                <div
                  style={{ display: "flex", alignItems: "center", gap: 10 }}
                >
                  <LIcon
                    name={uiTool.icon}
                    size={13}
                    color={t.textSub}
                  />
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                    }}
                  >
                    <span
                      style={{ fontSize: 12, color: t.text, fontWeight: 600 }}
                    >
                      {uiTool.label}
                    </span>
                    <span style={{ fontSize: 10.5, color: t.textSub }}>
                      {uiTool.description}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => removeTool(key)}
                  title="Remove tool"
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: "3px 5px",
                    borderRadius: 6,
                    display: "flex",
                    alignItems: "center",
                    color: t.textDim,
                    flexShrink: 0,
                    transition: "color 0.15s, background 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.color =
                      "#e05555";
                    (e.currentTarget as HTMLButtonElement).style.background =
                      "rgba(224,85,85,0.1)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.color =
                      t.textDim;
                    (e.currentTarget as HTMLButtonElement).style.background =
                      "none";
                  }}
                >
                  <LIcon name="X" size={13} color="currentColor" />
                </button>
              </div>
              );
            })}

            {/* Combined add row: text file / dataset / remaining capability toggles */}
            {(onAddFile || onAddDataset || availableToAdd.length > 0) && (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 6,
                  marginTop:
                    connectedSources.length > 0 || localTools.length > 0
                      ? 4
                      : 0,
                  paddingTop:
                    connectedSources.length > 0 || localTools.length > 0
                      ? 8
                      : 0,
                  borderTop:
                    connectedSources.length > 0 || localTools.length > 0
                      ? `1px dashed ${t.border}`
                      : undefined,
                }}
              >
                {onAddFile && (
                  <button
                    onClick={onAddFile}
                    style={{
                      display: "flex", alignItems: "center", gap: 5,
                      padding: "4px 10px", borderRadius: 20,
                      border: `1.5px dashed ${t.border}`,
                      background: "transparent", color: t.textSub,
                      fontSize: 11.5, fontFamily: "'Space Grotesk', sans-serif",
                      cursor: "pointer", transition: "all 0.15s",
                    }}
                    onMouseEnter={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.borderColor = t.borderHi; el.style.color = t.text; el.style.background = t.hover; }}
                    onMouseLeave={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.borderColor = t.border; el.style.color = t.textSub; el.style.background = "transparent"; }}
                  >
                    <LIcon name="Plus" size={11} color="currentColor" />
                    Add text file
                  </button>
                )}
                {onAddDataset && (
                  <button
                    onClick={onAddDataset}
                    style={{
                      display: "flex", alignItems: "center", gap: 5,
                      padding: "4px 10px", borderRadius: 20,
                      border: `1.5px dashed ${t.border}`,
                      background: "transparent", color: t.textSub,
                      fontSize: 11.5, fontFamily: "'Space Grotesk', sans-serif",
                      cursor: "pointer", transition: "all 0.15s",
                    }}
                    onMouseEnter={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.borderColor = t.borderHi; el.style.color = t.text; el.style.background = t.hover; }}
                    onMouseLeave={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.borderColor = t.border; el.style.color = t.textSub; el.style.background = "transparent"; }}
                  >
                    <LIcon name="Plus" size={11} color="currentColor" />
                    Add dataset
                  </button>
                )}
                {availableToAdd.map((uiTool) => (
                  <button
                    key={uiTool.key}
                    onClick={() => addTool(uiTool.key)}
                    title={`Add ${uiTool.label}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                      padding: "4px 10px",
                      borderRadius: 20,
                      border: `1.5px dashed ${t.border}`,
                      background: "transparent",
                      color: t.textSub,
                      fontSize: 11.5,
                      fontFamily: "'Space Grotesk', sans-serif",
                      cursor: "pointer",
                      transition: "all 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = t.borderHi;
                      el.style.color = t.text;
                      el.style.background = t.hover;
                    }}
                    onMouseLeave={(e) => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = t.border;
                      el.style.color = t.textSub;
                      el.style.background = "transparent";
                    }}
                  >
                    <LIcon name="Plus" size={11} color="currentColor" />
                    {uiTool.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </>

      {agent && agent.connections.length > 0 && (
        <>
          {dropdownHeader(
            "Connections",
            "Network",
            agent.connections.length,
            connsOpen,
            () => setConnsOpen((o) => !o),
          )}
          {connsOpen && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                marginTop: 4,
              }}
            >
              {agent.connections.map((id) => (
                <div
                  key={id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    background: t.inputBg,
                    border: `1.5px solid ${t.border}`,
                    borderRadius: 8,
                    padding: "7px 12px",
                  }}
                >
                  <LIcon name="Bot" size={12} color={t.textDim} />
                  <span
                    style={{
                      fontSize: 12,
                      color: t.textSub,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {getName(id)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 24,
          paddingTop: 16,
          borderTop: `1px solid ${t.border}`,
          gap: 10,
        }}
      >
        {agent ? (
          <FBtn
            variant="danger"
            onClick={() => onDelete(agent.id)}
            icon="Trash2"
          >
            Delete
          </FBtn>
        ) : (
          <div />
        )}
        <FBtn
          variant="primary"
          onClick={handleSave}
          icon={agent ? undefined : "Plus"}
        >
          {agent ? "Save Agent" : "Create Agent"}
        </FBtn>
      </div>
    </PanelShell>
  );
}
