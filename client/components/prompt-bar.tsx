"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { useApiKeys } from "@/lib/api-keys-context";
import { fetchModels } from "@/lib/api";
import { MarkdownRenderer } from "@/components/markdown-renderer";

interface PromptBarProps {
  running: boolean;
  turnCount: number;
  // Consensus mode, topology and fan-out now live in the Settings panel; the
  // prompt bar only collects the prompt and triggers the run.
  onRun: (prompt: string) => void;
  onResetContext: () => void;
  onOpenKeys: () => void;
  iterations?: number;
  onIterationsChange?: (n: number) => void;
  batchProgress?: { completed: number; total: number } | null;
  onHeightChange?: (h: number) => void;
}

export function PromptBar({
  running,
  turnCount,
  onRun,
  onResetContext,
  onOpenKeys,
  iterations = 1,
  onIterationsChange,
  batchProgress,
  onHeightChange,
}: PromptBarProps) {
  const [val, setVal] = useState("");
  const [preview, setPreview] = useState(false);
  const { dark } = useTheme();
  const t = getTheme(dark);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const { keys } = useApiKeys();
  const hasLocalKey = Object.values(keys).some((k) => k.length > 0);
  const [hasServerModels, setHasServerModels] = useState(false);

  useEffect(() => {
    fetchModels()
      .then((m) => setHasServerModels(m.length > 0))
      .catch(() => setHasServerModels(false));
  }, [hasLocalKey]);

  useEffect(() => {
    const el = rootRef.current;
    if (!el || !onHeightChange) return;
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height;
      if (h) onHeightChange(h);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [onHeightChange]);

  const hasAnyKey = hasLocalKey || hasServerModels;
  const inputDisabled = running || !hasAnyKey;
  const canRun = !running && hasAnyKey && val.trim().length > 0;

  const handleSubmit = useCallback(() => {
    if (!canRun) return;
    onRun(val);
    setVal("");
    setPreview(false);
  }, [canRun, onRun, val]);

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
      ref={rootRef}
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
        {/* Batch progress strip — shown inside the pill when running >1 trials */}
        {batchProgress && batchProgress.total > 1 && (
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              height: 3,
              borderRadius: "14px 14px 0 0",
              background: t.inputBg,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${
                  (batchProgress.completed / batchProgress.total) * 100
                }%`,
                background: BURG,
                transition: "width 0.4s ease",
                borderRadius: "14px 14px 0 0",
              }}
            />
          </div>
        )}
        <textarea
          ref={textareaRef}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={inputDisabled}
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
            color: inputDisabled ? t.textDim : t.text,
            caretColor: t.text,
            colorScheme: dark ? "dark" : "light",
            fontSize: 13.5,
            lineHeight: 1.55,
            opacity: inputDisabled ? 0.5 : 1,
            cursor: inputDisabled ? "not-allowed" : "text",
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

        {/* Iterations counter — ×N pill with +/- nudges */}
        {onIterationsChange && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              background: t.inputBg,
              border: `1px solid ${t.border}`,
              borderRadius: 100,
              padding: "2px 4px",
              flexShrink: 0,
            }}
          >
            <button
              type="button"
              onClick={() => onIterationsChange(Math.max(1, iterations - 1))}
              disabled={running || iterations <= 1}
              title="Fewer iterations"
              style={{
                background: "none",
                border: "none",
                color: iterations <= 1 ? t.textDim : t.textSub,
                cursor: iterations <= 1 ? "not-allowed" : "pointer",
                padding: "2px 5px",
                fontSize: 13,
                lineHeight: 1,
                borderRadius: 100,
                fontWeight: 700,
              }}
            >
              −
            </button>
            <span
              style={{
                color: iterations > 1 ? BURG_LT : t.textSub,
                fontSize: 11.5,
                fontWeight: 700,
                fontFamily: "'JetBrains Mono', monospace",
                minWidth: 20,
                textAlign: "center",
                letterSpacing: 0.2,
              }}
            >
              ×{iterations}
            </span>
            <button
              type="button"
              onClick={() => onIterationsChange(Math.min(10, iterations + 1))}
              disabled={running || iterations >= 10}
              title="More iterations"
              style={{
                background: "none",
                border: "none",
                color: iterations >= 10 ? t.textDim : t.textSub,
                cursor: iterations >= 10 ? "not-allowed" : "pointer",
                padding: "2px 5px",
                fontSize: 13,
                lineHeight: 1,
                borderRadius: 100,
                fontWeight: 700,
              }}
            >
              +
            </button>
          </div>
        )}

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
          {batchProgress && batchProgress.total > 1
            ? `${batchProgress.completed} / ${batchProgress.total}`
            : "Run"}
        </button>
      </div>

      {/* Conversation reset — only shown after at least one completed turn */}
      {turnCount > 0 && !running && (
        <button
          onClick={onResetContext}
          title="Start a fresh conversation"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: t.pill,
            border: `1px solid ${t.pillBorder}`,
            borderRadius: 100,
            padding: "4px 12px",
            cursor: "pointer",
            color: t.textSub,
            fontSize: 10.5,
            fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: 0.3,
            transition: "color 0.15s, border-color 0.15s",
          }}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLButtonElement;
            el.style.color = t.text;
            el.style.borderColor = BURG;
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLButtonElement;
            el.style.color = t.textSub;
            el.style.borderColor = t.pillBorder;
          }}
        >
          <LIcon name="RotateCcw" size={11} color="currentColor" />
          New conversation
          <span style={{ opacity: 0.6 }}>
            · {turnCount} turn{turnCount === 1 ? "" : "s"}
          </span>
        </button>
      )}

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
            ? "This AI system can make mistakes. Outputs may be incomplete or incorrect — always verify independently."
            : "This AI system can make mistakes. Add an API key (Keys button, top bar) to start running simulations."}
        </span>
      </div>
    </div>
  );
}
