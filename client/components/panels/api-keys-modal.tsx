"use client";

import { useState, useRef, useEffect } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import {
  useApiKeys,
  EMPTY_KEYS,
  OLLAMA_DEFAULT_ENDPOINT,
  type ApiKeys,
} from "@/lib/api-keys-context";
import { Checkbox } from "./panel-primitives";

const PROVIDERS = [
  { key: "openaiKey", label: "OpenAI" },
  { key: "anthropicKey", label: "Anthropic" },
  { key: "groqKey", label: "Groq" },
  { key: "geminiKey", label: "Gemini" },
  { key: "ollamaBaseUrl", label: "Ollama" },
  { key: "proxyKey", label: "Custom Proxy" },
] as const;

// Ollama is local and keyless: its field is an endpoint URL, not an API key.
const ENDPOINT_KEYS = new Set<string>(["ollamaBaseUrl"]);

export function ApiKeysModal({ onClose }: { onClose: () => void }) {
  const { keys, setKeys, clearKeys } = useApiKeys();
  const [draft, setDraft] = useState<ApiKeys>(keys);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const { dark } = useTheme();
  const t = getTheme(dark);

  const [activeIds, setActiveIds] = useState<Set<string>>(() => {
    const s = new Set<string>();
    PROVIDERS.forEach((p) => {
      if (keys[p.key as keyof ApiKeys]) s.add(p.key);
    });
    if (s.size === 0) s.add("openaiKey");
    return s;
  });

  const toggleProvider = (id: string) => {
    setActiveIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    // Ollama has no key, so enabling it must seed its endpoint — otherwise there
    // is nothing to persist and the X-LLM-Ollama-Base-Url header is never sent.
    if (id === "ollamaBaseUrl") {
      setDraft((d) =>
        d.ollamaBaseUrl ? d : { ...d, ollamaBaseUrl: OLLAMA_DEFAULT_ENDPOINT },
      );
    }
  };

  const update = (key: keyof ApiKeys, value: string) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const save = () => {
    const finalKeys = { ...draft };
    // Optionally wipe keys that are unchecked, but better to keep them if they just hid the input
    setKeys(finalKeys);
    onClose();
  };

  const clearAll = () => {
    setDraft(EMPTY_KEYS);
    clearKeys();
    setActiveIds(new Set(["openaiKey"]));
  };

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

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.45)",
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(480px, 92vw)",
          maxHeight: "85vh",
          overflowY: "auto",
          background: dark ? "rgba(14,12,22,0.98)" : "rgba(255,254,255,0.99)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 14,
          padding: 22,
          boxShadow: dark
            ? "0 12px 48px rgba(0,0,0,0.6)"
            : "0 12px 40px rgba(0,0,0,0.18)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 6,
          }}
        >
          <h2
            style={{ fontSize: 16, fontWeight: 700, color: t.text, margin: 0 }}
          >
            API Keys
          </h2>
          <button
            onClick={onClose}
            title="Close"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: t.textSub,
              display: "flex",
            }}
          >
            <LIcon name="X" size={16} color="currentColor" />
          </button>
        </div>

        <p
          style={{
            fontSize: 11.5,
            color: t.textSub,
            marginTop: 0,
            lineHeight: 1.5,
          }}
        >
          Keys are kept only in this browser tab (sessionStorage) and sent with
          each request. They are never stored on the server.
        </p>

        {/* Dropdown for selecting providers */}
        <div
          style={{ position: "relative", marginTop: 16, marginBottom: 16 }}
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
              padding: "10px 14px",
              cursor: "pointer",
              color: t.text,
              fontSize: 12.5,
              fontWeight: 500,
            }}
          >
            <span>Select Providers... ({activeIds.size})</span>
            <LIcon name="ChevronDown" size={16} color={t.textDim} />
          </div>

          {dropdownOpen && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: 0,
                right: 0,
                marginTop: 6,
                background: dark
                  ? "rgba(18,16,26,0.98)"
                  : "rgba(255,255,255,0.99)",
                border: `1px solid ${t.borderHi}`,
                borderRadius: 8,
                padding: "8px 0",
                zIndex: 10,
                boxShadow: dark
                  ? "0 8px 30px rgba(0,0,0,0.6)"
                  : "0 4px 20px rgba(0,0,0,0.1)",
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
                      gap: 12,
                      padding: "8px 16px",
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
                        fontSize: 12.5,
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

        {/* Dynamic Inputs */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {PROVIDERS.filter((p) => activeIds.has(p.key)).map((f) => {
            const isEndpoint = ENDPOINT_KEYS.has(f.key);
            return (
              <label
                key={f.key}
                style={{ display: "flex", flexDirection: "column", gap: 4 }}
              >
                <span
                  style={{
                    fontSize: 10.5,
                    fontWeight: 600,
                    letterSpacing: 0.3,
                    color: t.textSub,
                    fontFamily: "'JetBrains Mono', monospace",
                    textTransform: "uppercase",
                  }}
                >
                  {f.label} {isEndpoint ? "Endpoint" : "API Key"}
                </span>
                <input
                  type={isEndpoint ? "text" : "password"}
                  value={draft[f.key as keyof ApiKeys]}
                  onChange={(e) =>
                    update(f.key as keyof ApiKeys, e.target.value)
                  }
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={
                    isEndpoint ? "http://localhost:11434/v1" : "sk-…"
                  }
                  style={{
                    background: t.inputBg,
                    border: `1px solid ${t.border}`,
                    borderRadius: 8,
                    color: t.text,
                    fontSize: 12.5,
                    padding: "8px 11px",
                    outline: "none",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                />
              </label>
            );
          })}

          {activeIds.size === 0 && (
            <div
              style={{
                fontSize: 12,
                color: t.textDim,
                fontStyle: "italic",
                textAlign: "center",
                margin: "10px 0",
              }}
            >
              Please select a provider from the dropdown above.
            </div>
          )}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 24,
          }}
        >
          <button
            onClick={clearAll}
            style={{
              background: "none",
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              color: t.textSub,
              fontSize: 12,
              fontWeight: 600,
              padding: "8px 14px",
              cursor: "pointer",
            }}
          >
            Clear all keys
          </button>
          <button
            onClick={save}
            style={{
              background: BURG,
              border: "none",
              borderRadius: 8,
              color: "#fff",
              fontSize: 12.5,
              fontWeight: 700,
              padding: "8px 20px",
              cursor: "pointer",
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
