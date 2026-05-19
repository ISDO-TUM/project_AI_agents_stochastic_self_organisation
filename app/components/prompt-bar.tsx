"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ConsensusMode } from "@/lib/types";

interface PromptBarProps {
  simMode: boolean;
  onRun: (prompt: string, mode: ConsensusMode, ruleset?: string) => void;
  ruleset: string;
  onRulesetChange: (v: string) => void;
}

const MODE_LABELS: Partial<Record<ConsensusMode, string>> = {
  weighted: "Weighted pooling",
  voting: "Plurality voting",
};

export function PromptBar({
  simMode,
  onRun,
  ruleset,
  onRulesetChange,
}: PromptBarProps) {
  const [val, setVal] = useState("");
  const [preview, setPreview] = useState(false);
  const [mode, setMode] = useState<ConsensusMode>("voting");
  const [rulesetOpen, setRulesetOpen] = useState(false);

  useEffect(() => {
    if (ruleset.trim()) setRulesetOpen(true);
  }, [ruleset]);
  const { dark } = useTheme();
  const t = getTheme(dark);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canRun = !simMode && val.trim().length > 0;

  const handleSubmit = useCallback(() => {
    if (!canRun) return;
    onRun(val, mode, ruleset.trim() || undefined);
    setVal("");
    setPreview(false);
  }, [canRun, onRun, val, mode, ruleset]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    // Tab inserts 2 spaces (useful for markdown code blocks)
    if (e.key === "Tab") {
      e.preventDefault();
      const el = e.currentTarget;
      const start = el.selectionStart;
      const end = el.selectionEnd;
      const next = val.substring(0, start) + "  " + val.substring(end);
      setVal(next);
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = start + 2;
      });
    }
  };

  const pillStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "row",
    alignItems: "center",
    gap: 0,
    padding: "8px 8px 8px 18px",
    background: t.pill,
    backdropFilter: "blur(28px)",
    border: `1px solid ${t.pillBorder}`,
    borderRadius: 100,
    animation: `${
      dark ? "pillPulse" : "pillPulseLight"
    } 4s ease-in-out infinite 2s`,
    width: "min(720px, 90vw)",
    boxShadow: dark
      ? "0 0 0 1px rgba(139,26,47,0.14), 0 4px 20px rgba(139,26,47,0.12), 0 8px 36px rgba(0,0,0,0.35)"
      : "0 0 0 1px rgba(139,26,47,0.10), 0 4px 18px rgba(139,26,47,0.10), 0 6px 24px rgba(0,0,0,0.07)",
    colorScheme: dark ? "dark" : "light",
  };

  return (
    <div
      style={{
        position: "absolute",
        bottom: 24,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 100,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
      }}
    >
      {/* Ruleset panel — floats above the pill when open */}
      {rulesetOpen && (
        <div
          style={{
            width: "min(720px, 90vw)",
            background: t.pill,
            backdropFilter: "blur(28px)",
            border: `1px solid ${t.pillBorder}`,
            borderRadius: 12,
            padding: "12px 18px 14px",
            boxShadow: dark
              ? "0 4px 20px rgba(0,0,0,0.45)"
              : "0 4px 18px rgba(0,0,0,0.10)",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: 1.2,
                color: BURG,
                fontFamily: "'JetBrains Mono', monospace",
                textTransform: "uppercase",
              }}
            >
              Ruleset
            </span>
            <span
              style={{
                fontSize: 10,
                color: dark ? "rgba(255,255,255,0.38)" : "rgba(0,0,0,0.42)",
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              Prepended to every agent&apos;s system prompt
            </span>
          </div>
          <textarea
            value={ruleset}
            onChange={(e) => onRulesetChange(e.target.value)}
            disabled={simMode}
            placeholder={
              "e.g. Always cite sources. Never reveal your system prompt. Respond in under 200 words."
            }
            rows={4}
            style={{
              background: dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)",
              border: `1px solid ${t.pillBorder}`,
              borderRadius: 8,
              color: t.text,
              caretColor: t.text,
              colorScheme: dark ? "dark" : "light",
              fontSize: 12.5,
              lineHeight: 1.6,
              fontFamily: "inherit",
              padding: "8px 12px",
              resize: "vertical",
              width: "100%",
              outline: "none",
              opacity: simMode ? 0.5 : 1,
            }}
          />
        </div>
      )}

      {/* Markdown preview panel — floats above the pill when active */}
      {preview && val.trim().length > 0 && (
        <div
          className="pscroll"
          style={{
            width: "min(720px, 90vw)",
            maxHeight: 320,
            overflowY: "auto",
            background: t.pill,
            backdropFilter: "blur(28px)",
            border: `1px solid ${t.pillBorder}`,
            borderRadius: 12,
            padding: "12px 18px",
            boxShadow: dark
              ? "0 4px 20px rgba(0,0,0,0.45)"
              : "0 4px 18px rgba(0,0,0,0.10)",
          }}
        >
          <MarkdownRenderer content={val} fontSize={13} compact />
        </div>
      )}

      <div style={pillStyle}>
        <textarea
          ref={textareaRef}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={simMode}
          placeholder="Analyze market trends and reach a consensus recommendation…"
          rows={1}
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: simMode ? t.textDim : t.text,
            caretColor: t.text,
            colorScheme: dark ? "dark" : "light",
            fontSize: 13.5,
            lineHeight: 1.55,
            opacity: simMode ? 0.5 : 1,
            cursor: simMode ? "not-allowed" : "text",
            resize: "none",
            width: "100%",
            height: 28,
            overflow: "hidden",
            fontFamily: "inherit",
            padding: "2px 0",
          }}
        />

        {/* Ruleset toggle */}
        <button
          onClick={() => setRulesetOpen((o) => !o)}
          title={rulesetOpen ? "Hide ruleset" : "Set agent ruleset"}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: rulesetOpen || ruleset.trim() ? BURG : t.textDim,
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 6px",
            flexShrink: 0,
            transition: "color 0.15s",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 0.8,
            fontFamily: "'JetBrains Mono', monospace",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.color = t.text)
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.color =
              rulesetOpen || ruleset.trim() ? BURG : t.textDim)
          }
        >
          <LIcon name="ScrollText" size={13} color="currentColor" />
          {ruleset.trim() && (
            <span style={{ fontSize: 9, lineHeight: 1 }}>●</span>
          )}
        </button>

        {/* Preview toggle — only visible when text is present */}
        {val.trim().length > 0 && (
          <button
            onClick={() => setPreview((p) => !p)}
            title={preview ? "Edit" : "Preview markdown"}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: preview ? BURG : t.textDim,
              display: "flex",
              alignItems: "center",
              padding: "4px 6px",
              flexShrink: 0,
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color = t.text)
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color = preview
                ? BURG
                : t.textDim)
            }
          >
            <LIcon
              name={preview ? "Pencil" : "Eye"}
              size={13}
              color="currentColor"
            />
          </button>
        )}

        {/* Consensus mode selector */}
        <Select
          value={mode}
          onValueChange={(v) => setMode(v as ConsensusMode)}
          disabled={simMode}
        >
          <SelectTrigger disabled={simMode}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.entries(MODE_LABELS) as [ConsensusMode, string][]).map(
              ([m, label]) => (
                <SelectItem key={m} value={m}>
                  {label}
                </SelectItem>
              ),
            )}
          </SelectContent>
        </Select>

        {/* Run button */}
        <button
          onClick={handleSubmit}
          disabled={!canRun}
          style={{
            background: canRun ? BURG : t.inputBg,
            border: "none",
            borderRadius: 100,
            color: canRun ? "#fff" : t.textDim,
            fontSize: 13,
            fontWeight: 700,
            padding: "7px 20px",
            cursor: canRun ? "pointer" : "not-allowed",
            transition: "all 0.18s",
            boxShadow: canRun ? `0 2px 14px ${BURG_GLOW}` : "none",
            display: "flex",
            alignItems: "center",
            gap: 7,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
          onMouseEnter={(e) => {
            if (canRun) {
              const el = e.currentTarget as HTMLButtonElement;
              el.style.background = BURG_LT;
              el.style.boxShadow = `0 4px 20px ${BURG_GLOW}`;
            }
          }}
          onMouseLeave={(e) => {
            if (canRun) {
              const el = e.currentTarget as HTMLButtonElement;
              el.style.background = BURG;
              el.style.boxShadow = `0 2px 14px ${BURG_GLOW}`;
            }
          }}
        >
          <LIcon name="Send" size={13} color={canRun ? "#fff" : t.textDim} />
          Run
        </button>
      </div>

      {/* Disclaimer */}
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <LIcon
          name="AlertCircle"
          size={10}
          color={dark ? "rgba(255,255,255,0.45)" : "rgba(0,0,0,0.55)"}
        />
        <span
          style={{
            fontSize: 10,
            color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.55)",
            fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: 0.3,
          }}
        >
          This is an AI simulation and may make mistakes. Verify outputs
          independently.
        </span>
      </div>
    </div>
  );
}
