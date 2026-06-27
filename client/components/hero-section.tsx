"use client";

import dynamic from "next/dynamic";
import { ChevronDown } from "lucide-react";

// Loaded client-side only — WebGL requires the browser
const PlasmaWave = dynamic(() => import("@/components/plasma-wave"), {
  ssr: false,
});

// Burgundy palette — hero is always dark
const WAVE_COLORS: [string, string] = ["#8B1A2F", "#3D0B16"];

interface HeroSectionProps {
  onEnter: () => void;
}

export function HeroSection({ onEnter }: HeroSectionProps) {
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        background: "#060608",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      {/* ── Plasma wave fills the whole section ── */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          zIndex: 0,
          opacity: 0.88,
        }}
      >
        <PlasmaWave
          colors={WAVE_COLORS}
          speed1={0.04}
          speed2={0.035}
          focalLength={0.9}
          bend1={1.1}
          bend2={0.55}
          dir2={1}
          rotationDeg={-8}
        />
      </div>

      {/* ── Hero text ── */}
      <div
        style={{
          position: "relative",
          zIndex: 2,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 20,
          textAlign: "center",
          padding: "40px 56px",
          background: "transparent",
        }}
      >
        <h1
          style={{
            fontFamily: "var(--font-playfair), Georgia, serif",
            fontWeight: 900,
            fontStyle: "italic",
            fontSize: "clamp(3.5rem, 10vw, 8rem)",
            lineHeight: 1.0,
            letterSpacing: "-0.02em",
            color: "#eceaf5",
            userSelect: "none",
            textShadow:
              "0 2px 48px rgba(0,0,0,0.9), 0 0 80px rgba(139,26,47,0.4)",
          }}
        >
          Mycellium
        </h1>

        <p
          style={{
            fontFamily: "var(--font-space-grotesk), system-ui",
            fontWeight: 400,
            fontSize: "clamp(0.95rem, 2vw, 1.2rem)",
            color: "rgba(236,234,245,0.52)",
            letterSpacing: "0.01em",
            maxWidth: 460,
            lineHeight: 1.55,
            userSelect: "none",
            textShadow: "0 1px 12px rgba(0,0,0,0.95)",
          }}
        >
          Drop a new agent in.{" "}
          <span style={{ fontStyle: "italic" }}>It finds its place.</span> The
          system adapts.
        </p>
      </div>

      {/* ── Scroll-down arrow ── */}
      <button
        onClick={onEnter}
        aria-label="Enter the app"
        style={{
          position: "absolute",
          bottom: 36,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 3,
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "rgba(236,234,245,0.32)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 6,
          padding: 0,
          transition: "color 0.2s",
          fontFamily: "var(--font-space-grotesk), system-ui",
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.color =
            "rgba(236,234,245,0.72)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.color =
            "rgba(236,234,245,0.32)";
        }}
      >
        <span style={{ letterSpacing: "0.14em" }}>Enter</span>
        <ChevronDown
          size={20}
          strokeWidth={1.5}
          style={{ animation: "heroBounce 1.8s ease-in-out infinite" }}
        />
      </button>
    </div>
  );
}
