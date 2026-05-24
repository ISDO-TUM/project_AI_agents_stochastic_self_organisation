"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { useApiKeys } from "@/lib/api-keys-context";
import { fetchModels } from "@/lib/api";
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
  onRun: (prompt: string, mode: ConsensusMode) => void;
  onOpenKeys: () => void;
}

const MODE_LABELS: Partial<Record<ConsensusMode, string>> = {
  broadcast_no_consensus: "Broadcast",
  weighted_opinion_pooling: "Weighted pooling",
  plurality_voting: "Plurality voting",
};

export function PromptBar({ simMode, onRun, onOpenKeys }: PromptBarProps) {
  const [val, setVal] = useState("");
  const [preview, setPreview] = useState(false);
  const [mode, setMode] = useState<ConsensusMode>("plurality_voting");
  const { dark } = useTheme();
  const t = getTheme(dark);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { keys } = useApiKeys();
  const hasLocalKey = Object.values(keys).some((k) => k.length > 0);
  const [hasServerModels, setHasServerModels] = useState(false);

  useEffect(() => {
    fetchModels()
      .then((m) => setHasServerModels(m.length > 0))
      .catch(() => setHasServerModels(false));
  }, [hasLocalKey]);

  const hasAnyKey = hasLocalKey || hasServerModels;
  const canRun = !simMode && hasAnyKey && val.trim().length > 0;

  const handleSubmit = useCallback(() => {
    if (!canRun) return;
    onRun(val, mode);
    setVal("");
    setPreview(false);
  }, [canRun, onRun, val, mode]);

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

      {/* Hint for missing API keys */}
      {!hasAnyKey && (
        <div
          style={{
            fontSize: 11.5,
            color: BURG,
            background: dark ? "rgba(139,26,47,0.15)" : "rgba(139,26,47,0.08)",
            padding: "6px 12px",
            borderRadius: 8,
            marginBottom: 2,
            border: `1px solid ${
              dark ? "rgba(139,26,47,0.3)" : "rgba(139,26,47,0.15)"
            }`,
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontWeight: 500,
          }}
        >
          <LIcon name="KeyRound" size={12} color="currentColor" />
          <span>
            Please configure at least one API key in{" "}
            <button
              onClick={onOpenKeys}
              style={{
                background: "none",
                border: "none",
                color: BURG,
                textDecoration: "underline",
                cursor: "pointer",
                padding: 0,
                font: "inherit",
                fontWeight: 600,
              }}
            >
              settings
            </button>
            .
          </span>
        </div>
      )}

      <div style={pillStyle}>
        <textarea
          ref={textareaRef}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={simMode || !hasAnyKey}
          placeholder={
            hasAnyKey
              ? "Analyze market trends and reach a consensus recommendation…"
              : "API key required..."
          }
          rows={1}
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: simMode || !hasAnyKey ? t.textDim : t.text,
            caretColor: t.text,
            colorScheme: dark ? "dark" : "light",
            fontSize: 13.5,
            lineHeight: 1.55,
            opacity: simMode || !hasAnyKey ? 0.5 : 1,
            cursor: simMode || !hasAnyKey ? "not-allowed" : "text",
            resize: "none",
            width: "100%",
            height: 28,
            overflow: "hidden",
            fontFamily: "inherit",
            padding: "2px 0",
          }}
        />

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
          {hasAnyKey
            ? "This is an AI simulation and may make mistakes. Verify outputs independently."
            : "Add an API key (Keys button, top bar) to start running simulations."}
        </span>
      </div>
    </div>
  );
}
