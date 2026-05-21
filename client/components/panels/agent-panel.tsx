"use client";

import { useState, useMemo, useEffect } from "react";
import { Agent, Provider } from "@/lib/types";
import { uuid, shortId, PROVIDERS, TOOLS } from "@/lib/utils";
import { fetchModels, ModelEntry } from "@/lib/api";
import { BURG, BURG_LT, BURG_DIM, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon, TOOL_ICON } from "@/lib/icons";
import {
  FLabel,
  FInput,
  FSelect,
  FBtn,
  PanelShell,
  Checkbox,
} from "./panel-primitives";

interface AgentPanelProps {
  agent: Agent | null;
  agents: Agent[];
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
  tools: string[];
  connections: string[];
}

const defaultForm = (): AgentForm => ({
  name: "",
  description: "",
  provider: "openai",
  model: PROVIDERS["openai"].models[0].value,
  systemPrompt: "",
  tools: [],
  connections: [],
});

export function AgentPanel({
  agent,
  agents,
  onSave,
  onDelete,
  onClose,
}: AgentPanelProps) {
  const [availableModels, setAvailableModels] = useState<ModelEntry[]>([]);

  useEffect(() => {
    fetchModels().then(setAvailableModels).catch(console.error);
  }, []);

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

  useEffect(() => {
    if (!availableModels.length) return;
    setForm((f) => {
      const providerModels = providers[f.provider]?.models ?? [];
      const isValid = providerModels.some((m) => m.value === f.model);
      if (!isValid && providerModels.length > 0) {
        return { ...f, model: providerModels[0].value };
      }
      return f;
    });
  }, [availableModels, providers]);

  const [form, setForm] = useState<AgentForm>(
    agent
      ? {
          name: agent.name,
          description: agent.description,
          provider: agent.provider,
          model: agent.model,
          systemPrompt: agent.systemPrompt,
          tools: [...agent.tools],
          connections: [...agent.connections],
        }
      : defaultForm(),
  );
  const [connIn, setConnIn] = useState("");

  const set = <K extends keyof AgentForm>(k: K, v: AgentForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const toggleTool = (tool: string) =>
    set(
      "tools",
      form.tools.includes(tool)
        ? form.tools.filter((t) => t !== tool)
        : [...form.tools, tool],
    );

  const handleProv = (v: string) => {
    const provider = v as Provider;
    const firstModel = providers[provider]?.models[0]?.value ?? "";
    setForm((f) => ({
      ...f,
      provider,
      model: firstModel,
    }));
  };

  const addConn = () => {
    const val = connIn.trim();
    if (val && !form.connections.includes(val)) {
      set("connections", [...form.connections, val]);
      setConnIn("");
    }
  };

  const nameById = useMemo(
    () => new Map(agents.map((a) => [a.id, a.name])),
    [agents],
  );
  const getName = (id: string) => nameById.get(id) ?? `${shortId(id)}…`;

  const handleSave = () => {
    const position = agent?.position ?? {
      x: 220 + Math.random() * 480,
      y: 200 + Math.random() * 260,
    };
    onSave({ ...form, id: agent?.id ?? uuid(), position });
  };

  const { dark } = useTheme();
  const t = getTheme(dark);

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

      <FLabel>Tools</FLabel>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {TOOLS.map((tool) => {
          const active = form.tools.includes(tool);
          return (
            <div
              key={tool}
              role="checkbox"
              aria-checked={active}
              tabIndex={0}
              onClick={() => toggleTool(tool)}
              onKeyDown={(e) =>
                (e.key === " " || e.key === "Enter") && toggleTool(tool)
              }
              style={{
                display: "flex",
                alignItems: "center",
                gap: 11,
                cursor: "pointer",
                padding: "9px 12px",
                borderRadius: 10,
                border: `1.5px solid ${
                  active ? "rgba(139,26,47,0.38)" : t.border
                }`,
                background: active ? BURG_DIM : t.inputBg,
                transition: "all 0.15s",
              }}
            >
              <Checkbox checked={active} onChange={() => toggleTool(tool)} />
              <LIcon
                name={TOOL_ICON[tool] || "Wrench"}
                size={14}
                color={active ? BURG : t.textSub}
              />
              <span
                style={{
                  fontSize: 13,
                  color: t.text,
                  fontWeight: active ? 600 : 400,
                }}
              >
                {tool}
              </span>
            </div>
          );
        })}
      </div>

      <FLabel>Connections</FLabel>
      <div style={{ display: "flex", gap: 8 }}>
        <FInput
          value={connIn}
          onChange={setConnIn}
          placeholder="Node ID or name"
        />
        <button
          onClick={addConn}
          style={{
            flexShrink: 0,
            background: BURG,
            border: "none",
            color: "#fff",
            borderRadius: 10,
            width: 42,
            height: 42,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            transition: "background 0.15s",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = BURG_LT)
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = BURG)
          }
        >
          <LIcon name="Plus" size={18} color="#fff" />
        </button>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          marginTop: 8,
        }}
      >
        {form.connections.map((id) => (
          <div
            key={id}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: t.inputBg,
              border: `1.5px solid ${t.border}`,
              borderRadius: 9,
              padding: "8px 12px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <LIcon name="Network" size={12} color={t.textDim} />
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
            <button
              onClick={() =>
                set(
                  "connections",
                  form.connections.filter((c) => c !== id),
                )
              }
              style={{
                background: "none",
                border: "none",
                color: BURG_LT,
                cursor: "pointer",
                display: "flex",
                padding: 2,
                borderRadius: 5,
              }}
            >
              <LIcon name="X" size={13} color={BURG_LT} />
            </button>
          </div>
        ))}
      </div>

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
