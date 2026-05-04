"use client";

import { useState, useMemo } from "react";
import { Agent, Provider } from "@/lib/types";
import { uuid, shortId, PROVIDERS, TOOLS } from "@/lib/utils";
import { BURG, BURG_LT, BURG_DIM, getTheme } from "@/lib/theme";
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
  dark: boolean;
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
  model: "GPT-4o",
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
  dark,
}: AgentPanelProps) {
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
  const handleProv = (v: string) =>
    setForm((f) => ({
      ...f,
      provider: v as Provider,
      model: PROVIDERS[v].models[0],
    }));

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

  const t = getTheme(dark);

  return (
    <PanelShell
      title={agent ? "Configure Agent" : "New Agent"}
      onClose={onClose}
      dark={dark}
      icon={agent ? "Bot" : "Plus"}
    >
      <FLabel dark={dark}>Name</FLabel>
      <FInput
        value={form.name}
        onChange={(v) => set("name", v)}
        placeholder="Agent name"
        dark={dark}
      />
      <FLabel dark={dark}>Description</FLabel>
      <FInput
        value={form.description}
        onChange={(v) => set("description", v)}
        placeholder="What does this agent do?"
        dark={dark}
      />
      <FLabel dark={dark}>Provider</FLabel>
      <FSelect
        value={form.provider}
        onChange={handleProv}
        options={[
          { value: "openai", label: "OpenAI" },
          { value: "anthropic", label: "Anthropic" },
        ]}
        dark={dark}
      />
      <FLabel dark={dark}>Model</FLabel>
      <FSelect
        value={form.model}
        onChange={(v) => set("model", v)}
        options={PROVIDERS[form.provider].models.map((m) => ({
          value: m,
          label: m,
        }))}
        dark={dark}
      />
      <FLabel dark={dark}>System Prompt</FLabel>
      <FInput
        value={form.systemPrompt}
        onChange={(v) => set("systemPrompt", v)}
        placeholder="You are a helpful assistant…"
        multiline
        rows={5}
        dark={dark}
      />

      <FLabel dark={dark}>Tools</FLabel>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {TOOLS.map((tool) => {
          const active = form.tools.includes(tool);
          return (
            <div
              key={tool}
              onClick={() => toggleTool(tool)}
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
              <Checkbox
                checked={active}
                onChange={() => toggleTool(tool)}
                dark={dark}
              />
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

      <FLabel dark={dark}>Connections</FLabel>
      <div style={{ display: "flex", gap: 8 }}>
        <FInput
          value={connIn}
          onChange={setConnIn}
          placeholder="Node ID or name"
          dark={dark}
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
            dark={dark}
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
          dark={dark}
          icon={agent ? undefined : "Plus"}
        >
          {agent ? "Save Agent" : "Create Agent"}
        </FBtn>
      </div>
    </PanelShell>
  );
}
