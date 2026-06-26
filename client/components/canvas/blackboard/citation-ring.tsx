"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Heart, CheckCircle2 } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { Citer } from "@/lib/types";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";

interface CitationRingProps {
  count: number;
  threshold: number;
  variant: "ring" | "compact";
  citers?: Citer[];
  promotedRound?: number;
}

const SIZE = 28;
const STROKE = 3;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function ringColor(count: number, threshold: number): string {
  const pct = threshold > 0 ? count / threshold : 0;
  if (pct >= 1) return "#3dba8c";
  if (pct >= 0.5) return "#b5860d";
  return "rgba(139,26,47,0.35)";
}

export function CitationRing({
  count,
  threshold,
  variant,
  citers = [],
  promotedRound,
}: CitationRingProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const prevCount = useRef(count);
  const [pulseKey, setPulseKey] = useState(0);

  useEffect(() => {
    if (count > prevCount.current) setPulseKey((k) => k + 1);
    prevCount.current = count;
  }, [count]);

  if (promotedRound !== undefined) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          fontSize: 10.5,
          fontWeight: 700,
          color: "#3dba8c",
        }}
      >
        <CheckCircle2 size={12} strokeWidth={2} />
        Confirmed R{promotedRound}
      </span>
    );
  }

  const color = ringColor(count, threshold);
  const pct = Math.min(1, threshold > 0 ? count / threshold : 0);

  const body = (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      {variant === "ring" ? (
        <span style={{ position: "relative", width: SIZE, height: SIZE }}>
          <svg width={SIZE} height={SIZE}>
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)"}
              strokeWidth={STROKE}
            />
            <motion.circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={color}
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              initial={false}
              animate={{ strokeDashoffset: CIRCUMFERENCE * (1 - pct) }}
              transition={{ duration: 0.5, ease: "easeOut" }}
              transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            />
          </svg>
          <Heart
            size={11}
            strokeWidth={2}
            color={color}
            fill={pct >= 1 ? color : "none"}
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
            }}
          />
          {pulseKey > 0 && (
            <motion.span
              key={pulseKey}
              initial={{ opacity: 0.55, scale: 1 }}
              animate={{ opacity: 0, scale: 1.7 }}
              transition={{ duration: 0.6, ease: "easeOut" }}
              style={{
                position: "absolute",
                inset: 0,
                borderRadius: "50%",
                border: `1.5px solid ${color}`,
                pointerEvents: "none",
              }}
            />
          )}
        </span>
      ) : (
        <Heart
          size={11}
          strokeWidth={2}
          color={color}
          fill={pct >= 1 ? color : "none"}
        />
      )}
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textSub }}>
        {count} / {threshold}
      </span>
    </span>
  );

  if (citers.length === 0) return body;

  return (
    <HoverCard openDelay={120}>
      <HoverCardTrigger asChild>{body}</HoverCardTrigger>
      <HoverCardContent>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: t.textDim,
            marginBottom: 6,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          Cited by
        </div>
        {citers.map((c, i) => (
          <div
            key={`${c.agentName}-${i}`}
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 12,
              padding: "2px 0",
              color: t.text,
            }}
          >
            <span>{c.agentName}</span>
            <span style={{ color: t.textDim }}>R{c.round}</span>
          </div>
        ))}
        {pct < 1 && (
          <div style={{ marginTop: 6, fontSize: 10.5, color: t.textDim }}>
            {threshold - count} more citation
            {threshold - count === 1 ? "" : "s"} → Confirmed
          </div>
        )}
      </HoverCardContent>
    </HoverCard>
  );
}
