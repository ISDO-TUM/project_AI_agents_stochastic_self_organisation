"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import { Bell, Check } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { NotifyScope } from "@/lib/notifications";

const GOLD = "#b5860d";
const GOLD_LT = "#d8ad33";

interface NotifyConsentModalProps {
  /** Called with the user's choice: whether to notify, and how long to remember it. */
  onDecide: (enabled: boolean, scope: NotifyScope) => void;
}

/**
 * Asked once, when the first swarm run is launched: do you want a browser
 * notification when the final answer is ready, and should we remember that
 * always or only for this session? The run proceeds regardless — this is a
 * non-blocking opt-in shown over the canvas.
 */
export function NotifyConsentModal({ onDecide }: NotifyConsentModalProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [scope, setScope] = useState<NotifyScope>("always");

  if (typeof document === "undefined") return null;

  const scopeOption = (value: NotifyScope, label: string, sub: string) => {
    const active = scope === value;
    return (
      <motion.button
        type="button"
        onClick={() => setScope(value)}
        whileHover={{ y: -1 }}
        whileTap={{ scale: 0.985 }}
        style={{
          flex: 1,
          position: "relative",
          textAlign: "left",
          padding: "10px 12px",
          borderRadius: 11,
          cursor: "pointer",
          background: active
            ? dark
              ? "linear-gradient(160deg, rgba(216,173,51,0.18), rgba(181,134,13,0.08))"
              : "linear-gradient(160deg, rgba(216,173,51,0.16), rgba(181,134,13,0.05))"
            : dark
              ? "rgba(255,255,255,0.025)"
              : "rgba(0,0,0,0.015)",
          border: `1px solid ${active ? "rgba(181,134,13,0.55)" : t.border}`,
          boxShadow: active ? "0 4px 16px rgba(181,134,13,0.14)" : "none",
          transition: "background 0.18s, border-color 0.18s, box-shadow 0.18s",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <span
            style={{
              fontSize: 12.5,
              fontWeight: 700,
              color: active ? (dark ? GOLD_LT : GOLD) : t.text,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
            }}
          >
            {label}
          </span>
          <span
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: active ? GOLD : "transparent",
              border: active ? "none" : `1.5px solid ${t.border}`,
              transition: "background 0.18s, border-color 0.18s",
            }}
          >
            {active && <Check size={10} strokeWidth={3} color="#1a1405" />}
          </span>
        </div>
        <span
          style={{
            display: "block",
            marginTop: 2,
            fontSize: 10.5,
            color: t.textDim,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          {sub}
        </span>
      </motion.button>
    );
  };

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.22 }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background: dark
          ? "radial-gradient(120% 120% at 50% 0%, rgba(0,0,0,0.62), rgba(0,0,0,0.5))"
          : "radial-gradient(120% 120% at 50% 0%, rgba(245,242,232,0.6), rgba(230,224,210,0.42))",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.965 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 26 }}
        style={{
          position: "relative",
          width: "min(440px, 92vw)",
          borderRadius: 20,
          overflow: "hidden",
          background: dark
            ? "linear-gradient(180deg, rgba(22,18,8,0.98), rgba(12,10,4,0.98))"
            : "linear-gradient(180deg, rgba(255,254,249,0.99), rgba(252,248,238,0.99))",
          border: `1px solid ${
            dark ? "rgba(181,134,13,0.32)" : "rgba(181,134,13,0.28)"
          }`,
          boxShadow: dark
            ? "0 32px 90px rgba(0,0,0,0.6), 0 0 0 1px rgba(181,134,13,0.06), 0 0 70px rgba(181,134,13,0.07)"
            : "0 28px 80px rgba(80,60,10,0.18), 0 0 60px rgba(181,134,13,0.06)",
        }}
      >
        {/* Top accent line */}
        <div
          style={{
            height: 2.5,
            background:
              "linear-gradient(90deg, transparent, rgba(181,134,13,0.85), transparent)",
          }}
        />

        <div style={{ padding: "22px 24px 20px" }}>
          {/* ── Header: glowing bell badge + gradient title ── */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 14,
            }}
          >
            <motion.div
              initial={{ scale: 0.6, opacity: 0, rotate: -12 }}
              animate={{ scale: 1, opacity: 1, rotate: 0 }}
              transition={{
                delay: 0.06,
                type: "spring",
                stiffness: 360,
                damping: 18,
              }}
              style={{
                position: "relative",
                width: 42,
                height: 42,
                flexShrink: 0,
                borderRadius: 12,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background:
                  "radial-gradient(circle at 35% 30%, rgba(216,173,51,0.32), rgba(181,134,13,0.12))",
                border: "1px solid rgba(181,134,13,0.45)",
                boxShadow:
                  "0 6px 20px rgba(181,134,13,0.28), inset 0 1px 0 rgba(255,255,255,0.12)",
              }}
            >
              <Bell size={19} strokeWidth={2} color={dark ? GOLD_LT : GOLD} />
            </motion.div>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 16.5,
                  fontWeight: 700,
                  lineHeight: 1.2,
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  background: `linear-gradient(135deg, ${GOLD_LT}, ${GOLD})`,
                  WebkitBackgroundClip: "text",
                  backgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  color: "transparent",
                }}
              >
                Notify me when ready?
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: t.textDim,
                  marginTop: 2,
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                }}
              >
                Final answer · browser notification
              </div>
            </div>
          </div>

          <p
            style={{
              margin: "0 0 18px",
              fontSize: 13,
              lineHeight: 1.6,
              color: dark ? "rgba(235,230,218,0.78)" : "rgba(60,50,28,0.82)",
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
            }}
          >
            A swarm run can take a little while. With your permission,
            we&apos;ll ping you the moment the final answer is ready — no need
            to watch the board.
          </p>

          <div
            style={{
              fontSize: 9.5,
              fontWeight: 700,
              color: t.textDim,
              letterSpacing: "0.11em",
              textTransform: "uppercase",
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              marginBottom: 8,
            }}
          >
            Remember this choice
          </div>
          <div style={{ display: "flex", gap: 9, marginBottom: 20 }}>
            {scopeOption("always", "Always", "On every visit")}
            {scopeOption("session", "This session", "Until I leave")}
          </div>

          {/* ── Actions ── */}
          <div style={{ display: "flex", gap: 10 }}>
            <motion.button
              type="button"
              onClick={() => onDecide(false, scope)}
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.98 }}
              style={{
                flex: 1,
                padding: "11px 16px",
                borderRadius: 11,
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 600,
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                background: "transparent",
                border: `1px solid ${t.border}`,
                color: t.textDim,
              }}
            >
              Not now
            </motion.button>
            <motion.button
              type="button"
              onClick={() => onDecide(true, scope)}
              whileHover={{
                y: -1,
                boxShadow: "0 10px 28px rgba(181,134,13,0.4)",
              }}
              whileTap={{ scale: 0.98 }}
              style={{
                flex: 1.4,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 7,
                padding: "11px 16px",
                borderRadius: 11,
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 700,
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                background: `linear-gradient(135deg, ${GOLD_LT}, ${GOLD})`,
                border: "1px solid rgba(181,134,13,0.7)",
                color: "#1a1405",
                boxShadow: "0 6px 20px rgba(181,134,13,0.28)",
              }}
            >
              <Bell size={14} strokeWidth={2.4} />
              Enable notifications
            </motion.button>
          </div>

          <div
            style={{
              marginTop: 13,
              textAlign: "center",
              fontSize: 10.5,
              color: dark ? "rgba(235,230,218,0.4)" : "rgba(60,50,28,0.45)",
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
            }}
          >
            You can change this anytime in your browser settings.
          </div>
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  );
}
