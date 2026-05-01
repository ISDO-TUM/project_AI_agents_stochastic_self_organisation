"use client";

import { Tweaks } from "@/lib/types";
import { BURG, getTheme } from "@/lib/theme";
import { LIcon } from "@/lib/icons";
import { Toggle } from "./panels/panel-primitives";

interface TweaksPanelProps {
  tweaks: Tweaks;
  onChange: (key: keyof Tweaks, value: Tweaks[keyof Tweaks]) => void;
  onClose: () => void;
  dark: boolean;
}

const ACCENT_SWATCHES = ["#8B1A2F", "#1A3A8B", "#1A7A3A", "#6B1A8B", "#7A5A1A"];

export function TweaksPanel({
  tweaks,
  onChange,
  onClose,
  dark,
}: TweaksPanelProps) {
  const t = getTheme(dark);

  function Slider({
    label,
    k,
    min,
    max,
    step = 1,
    unit = "",
  }: {
    label: string;
    k: keyof Tweaks;
    min: number;
    max: number;
    step?: number;
    unit?: string;
  }) {
    return (
      <div style={{ marginBottom: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: 6,
          }}
        >
          <span style={{ fontSize: 12, color: t.textSub }}>{label}</span>
          <span
            style={{
              fontSize: 11,
              color: BURG,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {tweaks[k] as number}
            {unit}
          </span>
        </div>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={tweaks[k] as number}
          onChange={(e) => onChange(k, Number(e.target.value))}
          style={{ width: "100%", accentColor: BURG, cursor: "pointer" }}
        />
      </div>
    );
  }

  function Row({
    label,
    children,
  }: {
    label: string;
    children: React.ReactNode;
  }) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <span style={{ fontSize: 12, color: t.textSub }}>{label}</span>
        {children}
      </div>
    );
  }

  function Sec({
    title,
    children,
  }: {
    title: string;
    children: React.ReactNode;
  }) {
    return (
      <>
        <div
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: 1.4,
            textTransform: "uppercase",
            color: t.textDim,
            marginTop: 20,
            marginBottom: 12,
            paddingBottom: 7,
            borderBottom: `1px solid ${t.border}`,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {title}
        </div>
        {children}
      </>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        bottom: 96,
        left: 16,
        width: 264,
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px 10px",
          borderBottom: `1px solid ${t.border}`,
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

      <div
        style={{ padding: "4px 18px 18px", maxHeight: 420, overflowY: "auto" }}
      >
        <Sec title="Canvas">
          <Slider label="Node Size" k="nodeSize" min={60} max={120} unit="px" />
          <Slider
            label="Edge Width"
            k="edgeWidth"
            min={1}
            max={4}
            step={0.5}
            unit="px"
          />
          <Slider
            label="Grid Density"
            k="gridDensity"
            min={16}
            max={48}
            unit="px"
          />
          <Row label="Show Grid">
            <Toggle
              checked={tweaks.showGrid}
              onChange={() => onChange("showGrid", !tweaks.showGrid)}
              dark={dark}
            />
          </Row>
          <Row label="Ambient Orbs">
            <Toggle
              checked={tweaks.showOrbs}
              onChange={() => onChange("showOrbs", !tweaks.showOrbs)}
              dark={dark}
            />
          </Row>
        </Sec>

        <Sec title="Animation">
          <Slider
            label="Particle Speed"
            k="particleSpeed"
            min={0.3}
            max={2}
            step={0.1}
            unit="s"
          />
          <Row label="Pulse Rings">
            <Toggle
              checked={tweaks.showPulse}
              onChange={() => onChange("showPulse", !tweaks.showPulse)}
              dark={dark}
            />
          </Row>
        </Sec>

        <Sec title="Accent Color">
          <div
            style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}
          >
            {ACCENT_SWATCHES.map((col) => (
              <div
                key={col}
                onClick={() => onChange("accentColor", col)}
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: col,
                  cursor: "pointer",
                  border:
                    tweaks.accentColor === col
                      ? "2.5px solid #fff"
                      : "2.5px solid transparent",
                  transition: "all 0.15s",
                  boxShadow:
                    tweaks.accentColor === col ? `0 0 10px ${col}` : undefined,
                }}
              />
            ))}
          </div>
        </Sec>
      </div>
    </div>
  );
}
