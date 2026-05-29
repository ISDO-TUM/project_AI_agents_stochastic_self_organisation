"use client";

import { useState, useRef, useEffect } from "react";
import { ConsensusMode, Rule, TopologyMode } from "@/lib/types";
import { BURG, BURG_DIM, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon } from "@/lib/icons";
import { Checkbox } from "./panels/panel-primitives";
import { useApiKeys, EMPTY_KEYS, type ApiKeys } from "@/lib/api-keys-context";

const PROVIDERS = [
  { key: "openaiKey", label: "OpenAI" },
  { key: "anthropicKey", label: "Anthropic" },
  { key: "groqKey", label: "Groq" },
  { key: "geminiKey", label: "Gemini" },
  { key: "proxyKey", label: "Custom Proxy" },
] as const;

const CONSENSUS_LABELS: [ConsensusMode, string][] = [
  ["broadcast_no_consensus", "Broadcast"],
  ["weighted_opinion_pooling", "Weighted"],
  ["plurality_voting", "Plurality"],
];

type Theme = ReturnType<typeof getTheme>;

function FieldLabel({ text, t }: { text: string; t: Theme }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: 0.3,
        color: t.textSub,
        fontFamily: "'JetBrains Mono', monospace",
        textTransform: "uppercase",
        marginBottom: 7,
      }}
    >
      {text}
    </div>
  );
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
  t,
}: {
  options: [T, string][];
  value: T;
  onChange: (v: T) => void;
  disabled: boolean;
  t: Theme;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 6,
        background: t.inputBg,
        border: `1px solid ${t.border}`,
        borderRadius: 10,
        padding: 4,
      }}
    >
      {options.map(([val, label]) => {
        const active = val === value;
        return (
          <button
            key={val}
            type="button"
            disabled={disabled}
            onClick={() => onChange(val)}
            style={{
              flex: 1,
              background: active ? BURG : "transparent",
              border: "none",
              borderRadius: 7,
              color: active ? "#fff" : t.textSub,
              fontSize: 12,
              fontWeight: active ? 700 : 500,
              padding: "7px 8px",
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.5 : 1,
              transition: "all 0.15s",
              whiteSpace: "nowrap",
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

interface TweaksPanelProps {
  rules: Rule[];
  selectedRules: Set<string>;
  onToggleRule: (id: string) => void;
  consensusMode: ConsensusMode;
  onConsensusModeChange: (mode: ConsensusMode) => void;
  topology: TopologyMode;
  onTopologyChange: (topology: TopologyMode) => void;
  fanout: number;
  onFanoutChange: (fanout: number) => void;
  simRunning: boolean;
  onClose: () => void;
}

export function TweaksPanel({
  rules,
  selectedRules,
  onToggleRule,
  consensusMode,
  onConsensusModeChange,
  topology,
  onTopologyChange,
  fanout,
  onFanoutChange,
  simRunning,
  onClose,
}: TweaksPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [activeTab, setActiveTab] = useState<"sim" | "keys" | "rules">("sim");

  const { keys, setKeys, clearKeys } = useApiKeys();
  const [draft, setDraft] = useState<ApiKeys>(keys);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [activeIds, setActiveIds] = useState<Set<string>>(() => {
    const s = new Set<string>();
    PROVIDERS.forEach((p) => {
      if (keys[p.key as keyof ApiKeys]) s.add(p.key);
    });
    if (s.size === 0) s.add("openaiKey");
    return s;
  });

  const dropdownRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggleProvider = (id: string) => {
    setActiveIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const updateKey = (key: keyof ApiKeys, value: string) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const saveKeys = () => setKeys(draft);

  const clearAll = () => {
    setDraft(EMPTY_KEYS);
    clearKeys();
    setActiveIds(new Set(["openaiKey"]));
  };

  return (
    <div
      style={{
        position: "fixed",
        bottom: 96,
        left: 16,
        width: 340,
        background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,253,255,0.98)",
        backdropFilter: "blur(28px)",
        border: `1px solid ${t.borderHi}`,
        borderRadius: 18,
        zIndex: 300,
        boxShadow: dark
          ? "0 0 0 1px rgba(139,26,47,0.16), 0 20px 60px rgba(0,0,0,0.7)"
          : "0 0 0 1px rgba(139,26,47,0.10), 0 12px 40px rgba(0,0,0,0.12)",
        animation: "tweakSlide 0.22s cubic-bezier(0.22,1,0.36,1)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px 0",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <LIcon name="Settings2" size={14} color={BURG} />
          <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>
            Settings
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: t.textDim,
            display: "flex",
            padding: 4,
            borderRadius: 5,
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.color = t.text)
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.color = t.textDim)
          }
        >
          <LIcon name="X" size={14} color="currentColor" />
        </button>
      </div>

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          borderBottom: `1px solid ${t.border}`,
          marginTop: 10,
        }}
      >
        {(
          [
            { id: "sim", label: "Simulation", icon: "Settings2" },
            { id: "keys", label: "API Keys", icon: "KeyRound" },
            { id: "rules", label: "Rulesets", icon: "ScrollText" },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              flex: 1,
              background: "none",
              border: "none",
              borderBottom: `2px solid ${
                activeTab === tab.id ? BURG : "transparent"
              }`,
              padding: "9px 12px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              fontSize: 11.5,
              fontWeight: activeTab === tab.id ? 700 : 500,
              color: activeTab === tab.id ? BURG : t.textSub,
              transition: "all 0.15s",
            }}
          >
            <LIcon name={tab.icon} size={12} color="currentColor" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div
        className="pscroll"
        style={{
          padding: "14px 18px 18px",
          maxHeight: 440,
          overflowY: "auto",
        }}
      >
        {activeTab === "sim" && (
          <div>
            <p
              style={{
                fontSize: 11,
                color: t.textDim,
                lineHeight: 1.5,
                margin: "0 0 14px",
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              How agents agree and who they may talk to. Applied to the next
              run.
            </p>

            {/* Consensus mode */}
            <FieldLabel text="Consensus mode" t={t} />
            <Segmented
              options={CONSENSUS_LABELS}
              value={consensusMode}
              onChange={onConsensusModeChange}
              disabled={simRunning}
              t={t}
            />

            {/* Topology */}
            <div style={{ height: 14 }} />
            <FieldLabel text="Topology" t={t} />
            <Segmented
              options={[
                ["static", "Static"],
                ["dynamic", "Dynamic"],
              ]}
              value={topology}
              onChange={onTopologyChange}
              disabled={simRunning}
              t={t}
            />
            <p
              style={{
                fontSize: 10.5,
                color: t.textDim,
                lineHeight: 1.5,
                margin: "7px 0 0",
              }}
            >
              {topology === "dynamic"
                ? "Agents discover peers via the registry tool and rewire the graph each round."
                : "The connections drawn on the canvas stay fixed for the whole run."}
            </p>

            {/* Fan-out — only meaningful in dynamic mode. 0 == unlimited. */}
            {topology === "dynamic" && (
              <>
                <div style={{ height: 14 }} />
                <FieldLabel text="Fan-out" t={t} />
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    marginBottom: 8,
                  }}
                >
                  {fanout !== 0 && (
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={fanout}
                      disabled={simRunning}
                      onChange={(e) =>
                        onFanoutChange(
                          Math.max(
                            1,
                            Math.min(10, Number(e.target.value) || 1),
                          ),
                        )
                      }
                      style={{
                        width: 64,
                        background: t.inputBg,
                        border: `1px solid ${t.border}`,
                        borderRadius: 8,
                        color: t.text,
                        fontSize: 13,
                        fontWeight: 600,
                        padding: "8px 10px",
                        textAlign: "center",
                        outline: "none",
                      }}
                    />
                  )}
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 7,
                      cursor: simRunning ? "not-allowed" : "pointer",
                      opacity: simRunning ? 0.5 : 1,
                    }}
                  >
                    <Checkbox
                      checked={fanout === 0}
                      onChange={() => onFanoutChange(fanout === 0 ? 3 : 0)}
                    />
                    <span style={{ fontSize: 12, color: t.text }}>
                      Unlimited
                    </span>
                  </label>
                </div>
                <p
                  style={{
                    fontSize: 10.5,
                    color: t.textDim,
                    lineHeight: 1.5,
                    margin: 0,
                  }}
                >
                  {fanout === 0
                    ? "Unlimited: every agent may connect to all relevant peers it finds. Fine for small groups, but cost grows as O(n²) and the graph can get noisy with many agents."
                    : "A cap keeps each round at O(n·k) instead of O(n²): agents hear only their top matches, so token cost and noise stay bounded as the team grows. Lower it for large teams."}
                </p>
              </>
            )}
          </div>
        )}

        {activeTab === "keys" && (
          <div>
            <p
              style={{
                fontSize: 11,
                color: t.textDim,
                lineHeight: 1.5,
                margin: "0 0 14px",
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              Keys are stored in sessionStorage only and sent with each request.
              Never stored on the server.
            </p>

            {/* Provider dropdown */}
            <div
              style={{ position: "relative", marginBottom: 14 }}
              ref={dropdownRef}
            >
              <div
                onClick={() => setDropdownOpen((o) => !o)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: t.inputBg,
                  border: `1px solid ${t.border}`,
                  borderRadius: 8,
                  padding: "9px 12px",
                  cursor: "pointer",
                  color: t.text,
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                <span>Select providers… ({activeIds.size})</span>
                <LIcon name="ChevronDown" size={14} color={t.textDim} />
              </div>

              {dropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "calc(100% + 4px)",
                    left: 0,
                    right: 0,
                    background: dark
                      ? "rgba(18,16,26,0.98)"
                      : "rgba(255,255,255,0.99)",
                    border: `1px solid ${t.borderHi}`,
                    borderRadius: 8,
                    padding: "6px 0",
                    zIndex: 10,
                    boxShadow: dark
                      ? "0 8px 24px rgba(0,0,0,0.6)"
                      : "0 4px 16px rgba(0,0,0,0.1)",
                  }}
                >
                  {PROVIDERS.map((p) => {
                    const active = activeIds.has(p.key);
                    return (
                      <div
                        key={p.key}
                        onClick={() => toggleProvider(p.key)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: "7px 14px",
                          cursor: "pointer",
                          background: active
                            ? dark
                              ? "rgba(255,255,255,0.04)"
                              : "rgba(0,0,0,0.03)"
                            : "transparent",
                        }}
                      >
                        <Checkbox
                          checked={active}
                          onChange={() => toggleProvider(p.key)}
                        />
                        <span
                          style={{
                            fontSize: 12,
                            color: t.text,
                            fontWeight: active ? 600 : 400,
                          }}
                        >
                          {p.label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Key inputs */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {PROVIDERS.filter((p) => activeIds.has(p.key)).map((f) => (
                <label
                  key={f.key}
                  style={{ display: "flex", flexDirection: "column", gap: 3 }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      letterSpacing: 0.3,
                      color: t.textSub,
                      fontFamily: "'JetBrains Mono', monospace",
                      textTransform: "uppercase",
                    }}
                  >
                    {f.label} API Key
                  </span>
                  <input
                    type="password"
                    value={draft[f.key as keyof ApiKeys]}
                    onChange={(e) =>
                      updateKey(f.key as keyof ApiKeys, e.target.value)
                    }
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="sk-…"
                    style={{
                      background: t.inputBg,
                      border: `1px solid ${t.border}`,
                      borderRadius: 7,
                      color: t.text,
                      fontSize: 12,
                      padding: "7px 10px",
                      outline: "none",
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  />
                </label>
              ))}

              {activeIds.size === 0 && (
                <div
                  style={{
                    fontSize: 11.5,
                    color: t.textDim,
                    fontStyle: "italic",
                    textAlign: "center",
                    margin: "8px 0",
                  }}
                >
                  Select a provider above.
                </div>
              )}
            </div>

            {/* Save / Clear */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginTop: 18,
              }}
            >
              <button
                onClick={clearAll}
                style={{
                  background: "none",
                  border: `1px solid ${t.border}`,
                  borderRadius: 8,
                  color: t.textSub,
                  fontSize: 11.5,
                  fontWeight: 600,
                  padding: "7px 12px",
                  cursor: "pointer",
                }}
              >
                Clear all
              </button>
              <button
                onClick={saveKeys}
                style={{
                  background: BURG,
                  border: "none",
                  borderRadius: 8,
                  color: "#fff",
                  fontSize: 12,
                  fontWeight: 700,
                  padding: "7px 18px",
                  cursor: "pointer",
                }}
              >
                Save
              </button>
            </div>
          </div>
        )}

        {activeTab === "rules" && (
          <div>
            <p
              style={{
                fontSize: 11,
                color: t.textDim,
                lineHeight: 1.5,
                margin: "0 0 14px",
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              Checked rules are joined as bullet points and prepended to every
              agent&apos;s system prompt.
            </p>

            {rules.length === 0 && (
              <div
                style={{
                  fontSize: 12,
                  color: t.textDim,
                  padding: "20px 0",
                  textAlign: "center",
                }}
              >
                No rules available.
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {rules.map((rule) => {
                const active = selectedRules.has(rule.id);
                return (
                  <div
                    key={rule.id}
                    role="checkbox"
                    aria-checked={active}
                    tabIndex={0}
                    onClick={() => onToggleRule(rule.id)}
                    onKeyDown={(e) =>
                      (e.key === " " || e.key === "Enter") &&
                      onToggleRule(rule.id)
                    }
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      cursor: "pointer",
                      padding: "10px 12px",
                      borderRadius: 10,
                      border: `1.5px solid ${
                        active ? "rgba(139,26,47,0.38)" : t.border
                      }`,
                      background: active ? BURG_DIM : t.inputBg,
                      transition: "all 0.15s",
                    }}
                  >
                    <div style={{ paddingTop: 1, flexShrink: 0 }}>
                      <Checkbox
                        checked={active}
                        onChange={() => onToggleRule(rule.id)}
                      />
                    </div>
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                        minWidth: 0,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 13,
                          color: t.text,
                          fontWeight: active ? 600 : 500,
                        }}
                      >
                        {rule.label}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: t.textSub,
                          lineHeight: 1.5,
                        }}
                      >
                        {rule.instruction}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
