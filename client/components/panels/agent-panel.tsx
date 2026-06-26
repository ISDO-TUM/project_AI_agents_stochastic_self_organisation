"use client";

import { useState, useMemo, useEffect } from "react";
import { Agent, Provider, Source, Edge } from "@/lib/types";
import { uuid, shortId, PROVIDERS, TOOLS } from "@/lib/utils";
import { fetchModels, ModelEntry } from "@/lib/api";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { useApiKeys } from "@/lib/api-keys-context";
import { LIcon, TOOL_ICON } from "@/lib/icons";
import { FLabel, FInput, FSelect, FBtn, PanelShell } from "./panel-primitives";

interface AgentPanelProps {
  agent: Agent | null;
  agents: Agent[];
  sources: Source[];
  edges: Edge[];
  onSave: (agent: Agent) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
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

const TOOL_LABELS: Record<string, { label: string; description: string }> = {
  files: { label: "Files", description: "Read content from attached files." },
  table_query: {
    label: "Table Query",
    description: "Read rows from a connected dataset.",
  },
  table_mutate: {
    label: "Table Mutate",
    description: "Insert or update rows in a connected dataset.",
  },
};

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
    () => (agent?.tools ?? []).filter((tool) => TOOLS.includes(tool)),
    [agent],
  );

  const handleSave = () => {
    const position = agent?.position ?? {
      x: 220 + Math.random() * 480,
      y: 200 + Math.random() * 260,
    };
    onSave({
      ...form,
      id: agent?.id ?? uuid(),
      position,
      tools: agent?.tools ?? [],
      connections: agent?.connections ?? [],
    });
  };

  const [connsOpen, setConnsOpen] = useState(false);

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

      {(connectedSources.length > 0 || generalTools.length > 0) && (
        <>
          <FLabel>Tools</FLabel>
          {connectedSources.length > 0 && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                marginBottom: generalTools.length > 0 ? 10 : 0,
              }}
            >
              {connectedSources.map((src) => (
                <div
                  key={src.id}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 3,
                    padding: "8px 12px",
                    borderRadius: 8,
                    border: `1.5px solid ${t.border}`,
                    background: t.inputBg,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <LIcon
                      name={src.type === "dataset" ? "Table2" : "FileText"}
                      size={13}
                      color={t.textSub}
                    />
                    <span style={{ fontSize: 12, color: t.text, fontWeight: 600 }}>
                      {src.name}
                    </span>
                    <span
                      style={{
                        fontSize: 9.5,
                        color: t.textDim,
                        textTransform: "uppercase",
                        marginLeft: "auto",
                      }}
                    >
                      {src.type}
                    </span>
                  </div>
                  {src.content && (
                    <span style={{ fontSize: 11, color: t.textSub }}>
                      {truncateContent(src.content)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {generalTools.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {generalTools.map((tool) => (
                <div
                  key={tool}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 12px",
                    borderRadius: 8,
                    border: `1.5px solid ${t.border}`,
                    background: t.inputBg,
                  }}
                >
                  <LIcon name={TOOL_ICON[tool] || "Wrench"} size={13} color={t.textSub} />
                  <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                    <span style={{ fontSize: 12, color: t.text, fontWeight: 600 }}>
                      {TOOL_LABELS[tool]?.label ?? tool}
                    </span>
                    <span style={{ fontSize: 10.5, color: t.textSub }}>
                      {TOOL_LABELS[tool]?.description ?? ""}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

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
