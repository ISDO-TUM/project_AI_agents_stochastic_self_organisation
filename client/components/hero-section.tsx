"use client";

import dynamic from "next/dynamic";
import { useTheme } from "@/lib/theme-context";
import { ChevronDown, Sun, Moon } from "lucide-react";

// Loaded client-side only — WebGL requires the browser
const PlasmaWave = dynamic(() => import("@/components/plasma-wave"), {
  ssr: false,
});

// Light burgundy + dark burgundy for the plasma waves
const COLORS_DARK: [string, string] = ["#8B1A2F", "#3D0B16"];
const COLORS_LIGHT: [string, string] = ["#C4374F", "#8B1A2F"];

interface HeroSectionProps {
  onEnter: () => void;
}

export function HeroSection({ onEnter }: HeroSectionProps) {
  const { dark, toggle } = useTheme();

  const bg = dark ? "#060608" : "#faf8ff";
  const titleColor = dark ? "#f5f3ff" : "#0a0810";
  const subtitleColor = dark ? "rgba(245,243,255,0.55)" : "rgba(10,8,16,0.5)";
  const enterColor = dark ? "rgba(245,243,255,0.35)" : "rgba(10,8,16,0.3)";
  const enterHoverColor = dark ? "rgba(245,243,255,0.7)" : "rgba(10,8,16,0.65)";

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        background: bg,
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
          opacity: dark ? 0.9 : 0.75,
        }}
      >
        <PlasmaWave
          colors={dark ? COLORS_DARK : COLORS_LIGHT}
          speed1={0.04}
          speed2={0.035}
          focalLength={0.9}
          bend1={1.1}
          bend2={0.55}
          dir2={1}
          rotationDeg={-8}
        />
      </div>

      {/* ── Theme toggle — top right ── */}
      <button
        onClick={toggle}
        aria-label="Toggle theme"
        style={{
          position: "absolute",
          top: 20,
          right: 24,
          zIndex: 10,
          background: dark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.06)",
          border: dark
            ? "1px solid rgba(255,255,255,0.14)"
            : "1px solid rgba(0,0,0,0.1)",
          borderRadius: 40,
          padding: "7px 14px",
          display: "flex",
          alignItems: "center",
          gap: 7,
          cursor: "pointer",
          backdropFilter: "blur(8px)",
          transition: "background 0.2s",
          color: dark ? "rgba(245,243,255,0.7)" : "rgba(10,8,16,0.55)",
          fontSize: 12,
          fontWeight: 500,
          fontFamily: "var(--font-space-grotesk), system-ui",
          letterSpacing: "0.03em",
        }}
      >
        {dark ? (
          <>
            <Sun size={13} strokeWidth={2} />
            Light
          </>
        ) : (
          <>
            <Moon size={13} strokeWidth={2} />
            Dark
          </>
        )}
      </button>

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
          // subtle frosted card so text is legible over any wave colour
          background: dark ? "rgba(6,6,8,0.38)" : "rgba(250,248,255,0.38)",
          backdropFilter: "blur(2px)",
          borderRadius: 24,
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
            color: titleColor,
            userSelect: "none",
            textShadow: dark
              ? "0 2px 40px rgba(139,26,47,0.5)"
              : "0 2px 30px rgba(139,26,47,0.25)",
          }}
        >
          Mycellium
        </h1>

        <p
          style={{
            fontFamily: "var(--font-space-grotesk), system-ui",
            fontWeight: 400,
            fontSize: "clamp(0.95rem, 2vw, 1.2rem)",
            color: subtitleColor,
            letterSpacing: "0.01em",
            maxWidth: 460,
            lineHeight: 1.55,
            userSelect: "none",
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
          color: enterColor,
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
          (e.currentTarget as HTMLElement).style.color = enterHoverColor;
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.color = enterColor;
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
