"use client";

import { useRef, useState } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

interface ToolbarProps {
  simMode: boolean;
  onToggleTheme: () => void;
  onAddAgent: () => void;
  onAddFile: () => void;
  onClear: () => void;
  onStop: () => void;
  onAutoLayout: () => void;
  onExport: () => void;
  onImport: (raw: string) => void;
  onOpenHistory: () => void;
  showTweaks: boolean;
  onToggleTweaks: () => void;
}

function Sep({ t }: { t: ReturnType<typeof getTheme> }) {
  return (
    <div
      style={{ width: 1, height: 18, background: t.border, margin: "0 3px" }}
    />
  );
}

function TBtn({
  children,
  onClick,
  icon,
  title,
  active,
  danger,
  t,
}: {
  children?: React.ReactNode;
  onClick: () => void;
  icon?: string;
  title?: string;
  active?: boolean;
  danger?: boolean;
  t: ReturnType<typeof getTheme>;
}) {
  const [hov, setHov] = useState(false);
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background:
          hov || active
            ? active
              ? "rgba(139,26,47,0.18)"
              : t.hover
            : "transparent",
        border: "none",
        borderRadius: 8,
        color: danger
          ? hov
            ? BURG_LT
            : BURG
          : hov || active
            ? t.text
            : t.textSub,
        fontSize: 12,
        fontWeight: 600,
        padding: "6px 11px",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 6,
        transition: "all 0.15s",
        whiteSpace: "nowrap",
      }}
    >
      {icon && <LIcon name={icon} size={14} color="currentColor" />}
      {children}
    </button>
  );
}

function ToolsDropdown({
  onAddFile,
  t,
}: {
  onAddFile: () => void;
  t: ReturnType<typeof getTheme>;
}) {
  const [open, setOpen] = useState(false);
  const { dark } = useTheme();

  return (
    <div style={{ position: "relative" }}>
      <TBtn
        onClick={() => setOpen((x) => !x)}
        icon="Wrench"
        title="Tools"
        active={open}
        t={t}
      >
        Tools
      </TBtn>
      {open && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: 98 }}
            onClick={() => setOpen(false)}
          />
          <div
            style={{
              position: "absolute",
              top: "calc(100% + 6px)",
              left: "50%",
              transform: "translateX(-50%)",
              background: dark
                ? "rgba(12,10,22,0.97)"
                : "rgba(255,254,255,0.98)",
              border: `1px solid ${t.borderHi}`,
              borderRadius: 10,
              padding: "5px 0",
              minWidth: 140,
              zIndex: 99,
              boxShadow: dark
                ? "0 8px 32px rgba(0,0,0,0.55)"
                : "0 8px 24px rgba(0,0,0,0.12)",
              animation: "fadeIn 0.15s ease-out",
            }}
          >
            <button
              onClick={() => {
                setOpen(false);
                onAddFile();
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 9,
                width: "100%",
                background: "none",
                border: "none",
                color: t.textSub,
                fontSize: 12,
                fontWeight: 600,
                padding: "8px 14px",
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.12s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background =
                  t.hover;
                (e.currentTarget as HTMLButtonElement).style.color = t.text;
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background =
                  "none";
                (e.currentTarget as HTMLButtonElement).style.color = t.textSub;
              }}
            >
              <LIcon name="FileText" size={13} color="currentColor" />
              Files
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function Toolbar({
  simMode,
  onToggleTheme,
  onAddAgent,
  onAddFile,
  onClear,
  onStop,
  onAutoLayout,
  onExport,
  onImport,
  onOpenHistory,
  showTweaks,
  onToggleTweaks,
}: ToolbarProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const fileRef = useRef<HTMLInputElement>(null);

  const pillStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "8px 14px",
    background: t.pill,
    backdropFilter: "blur(28px)",
    border: `1px solid ${t.pillBorder}`,
    borderRadius: 100,
    animation: `${
      dark ? "pillPulse" : "pillPulseLight"
    } 4s ease-in-out infinite`,
    boxShadow: dark
      ? "0 0 0 1px rgba(139,26,47,0.14), 0 4px 20px rgba(139,26,47,0.12), 0 8px 36px rgba(0,0,0,0.35)"
      : "0 0 0 1px rgba(139,26,47,0.10), 0 4px 18px rgba(139,26,47,0.10), 0 6px 24px rgba(0,0,0,0.07)",
  };

  return (
    <div
      style={{
        position: "absolute",
        top: 16,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 100,
        display: "flex",
        gap: 8,
      }}
    >
      <div style={pillStyle}>
        {/* Logo */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 9,
            paddingRight: 8,
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <polygon
              points="12,2 21,6.5 21,17.5 12,22 3,17.5 3,6.5"
              fill="none"
              stroke={BURG}
              strokeWidth="1.5"
            />
            <polygon
              points="12,7 17,9.5 17,14.5 12,17 7,14.5 7,9.5"
              fill={BURG}
              opacity={0.22}
            />
            <circle cx="12" cy="12" r="2.5" fill={BURG} opacity={0.9} />
          </svg>
          <span
            style={{
              fontWeight: 700,
              fontSize: 13.5,
              color: t.text,
              letterSpacing: 0.4,
            }}
          >
            Stochastic Agents
          </span>
        </div>

        <Sep t={t} />

        {!simMode && (
          <>
            <TBtn onClick={onAddAgent} icon="Plus" title="Add Agent" t={t}>
              Agent
            </TBtn>
            <ToolsDropdown onAddFile={onAddFile} t={t} />
            <Sep t={t} />
            <TBtn
              onClick={onAutoLayout}
              icon="Shuffle"
              title="Auto-layout"
              t={t}
            >
              Layout
            </TBtn>
            <TBtn onClick={onExport} icon="Download" title="Export JSON" t={t}>
              Export
            </TBtn>
            <TBtn
              onClick={() => fileRef.current?.click()}
              icon="Upload"
              title="Import JSON"
              t={t}
            >
              Import
            </TBtn>
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  const reader = new FileReader();
                  reader.onload = (ev) => onImport(ev.target?.result as string);
                  reader.readAsText(file);
                }
                e.target.value = "";
              }}
            />
            <TBtn
              onClick={onOpenHistory}
              icon="Database"
              title="Simulation history"
              t={t}
            >
              History
            </TBtn>
            <Sep t={t} />
            <TBtn
              onClick={onToggleTweaks}
              icon="Settings2"
              title="Settings"
              active={showTweaks}
              t={t}
            >
              Settings
            </TBtn>
            <TBtn
              onClick={onClear}
              icon="Trash2"
              title="Clear canvas"
              danger
              t={t}
            >
              Clear
            </TBtn>
          </>
        )}

        {simMode && (
          <TBtn onClick={onStop} icon="Square" danger t={t}>
            Stop
          </TBtn>
        )}

        <Sep t={t} />

        <button
          onClick={onToggleTheme}
          title="Toggle theme"
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
          <LIcon name={dark ? "Sun" : "Moon"} size={15} color="currentColor" />
        </button>
      </div>
    </div>
  );
}
