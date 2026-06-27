"use client";

import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BURG, BURG_DIM, BURG_LT, getTheme } from "@/lib/theme";
import { LIcon } from "@/lib/icons";
import { useTheme } from "@/lib/theme-context";

/** Centered, auto-dismissing toast — shared by anything that needs a brief,
 *  non-blocking message (panel save-validation, import errors, etc.). */
export function Toast({
  message,
  onDone,
}: {
  message: string;
  onDone: () => void;
}) {
  useEffect(() => {
    const id = setTimeout(onDone, 4000);
    return () => clearTimeout(id);
  }, [onDone]);

  return createPortal(
    <div
      style={{
        position: "fixed",
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        zIndex: 9999,
        background: BURG,
        color: "#fff",
        padding: "13px 22px",
        borderRadius: 10,
        fontSize: 13,
        fontWeight: 600,
        boxShadow: "0 8px 32px rgba(0,0,0,0.45)",
        animation: "fadeIn 0.18s ease-out",
        maxWidth: 420,
        textAlign: "center",
        pointerEvents: "none",
      }}
    >
      {message}
    </div>,
    document.body,
  );
}

export function Checkbox({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: () => void;
}) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <div
      role="checkbox"
      aria-checked={checked}
      tabIndex={0}
      onClick={onChange}
      onKeyDown={(e) => (e.key === " " || e.key === "Enter") && onChange()}
      style={{
        width: 18,
        height: 18,
        borderRadius: 5,
        border: `1.5px solid ${checked ? BURG : t.borderHi}`,
        background: checked ? BURG : t.inputBg,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "all 0.15s",
        flexShrink: 0,
        boxShadow: checked ? `0 0 8px ${BURG_DIM}` : "none",
      }}
    >
      {checked && (
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#fff"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ animation: "checkPop 0.18s ease-out" }}
        >
          <path d="M20 6L9 17l-5-5" />
        </svg>
      )}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: () => void;
}) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <div
      role="switch"
      aria-checked={checked}
      tabIndex={0}
      onClick={onChange}
      onKeyDown={(e) => (e.key === " " || e.key === "Enter") && onChange()}
      style={{
        width: 38,
        height: 22,
        borderRadius: 11,
        background: checked ? BURG : t.inputBg,
        border: `1.5px solid ${checked ? BURG : t.border}`,
        cursor: "pointer",
        position: "relative",
        transition: "all 0.2s",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 17 : 2,
          width: 14,
          height: 14,
          borderRadius: "50%",
          background: checked ? "#fff" : "rgba(255,255,255,0.4)",
          transition: "left 0.2s",
          boxShadow: "0 1px 4px rgba(0,0,0,0.3)",
        }}
      />
    </div>
  );
}

export function FLabel({ children }: { children: React.ReactNode }) {
  const { dark } = useTheme();
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.3,
        textTransform: "uppercase",
        color: getTheme(dark).textDim,
        marginBottom: 8,
        marginTop: 20,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {children}
    </div>
  );
}

interface FInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  rows?: number;
}

export function FInput({
  value,
  onChange,
  placeholder,
  multiline,
  rows = 4,
}: FInputProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const base: React.CSSProperties = {
    width: "100%",
    background: t.inputBg,
    border: `1.5px solid ${t.border}`,
    borderRadius: 10,
    color: t.text,
    fontSize: 13,
    padding: "10px 13px",
    outline: "none",
    resize: multiline ? "vertical" : "none",
    lineHeight: 1.55,
    fontFamily: multiline
      ? "'JetBrains Mono', monospace"
      : "'Space Grotesk', sans-serif",
    transition: "border-color 0.15s, box-shadow 0.15s",
    boxSizing: "border-box",
  };
  const onFocus = (
    e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    e.target.style.borderColor = BURG;
    e.target.style.boxShadow = `0 0 0 3px ${BURG_DIM}`;
  };
  const onBlur = (
    e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    e.target.style.borderColor = t.border;
    e.target.style.boxShadow = "none";
  };
  if (multiline) {
    return (
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        style={base}
        onFocus={onFocus}
        onBlur={onBlur}
      />
    );
  }
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      style={base}
      onFocus={onFocus}
      onBlur={onBlur}
    />
  );
}

interface FSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}

export function FSelect({ value, onChange, options }: FSelectProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: "100%",
        background: t.inputBg,
        border: `1.5px solid ${t.border}`,
        borderRadius: 10,
        color: t.text,
        fontSize: 13,
        padding: "10px 34px 10px 13px",
        outline: "none",
        cursor: "pointer",
        boxSizing: "border-box",
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236B6880'/%3E%3C/svg%3E")`,
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 13px center",
        transition: "border-color 0.15s",
        appearance: "none",
      }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

interface FBtnProps {
  children: React.ReactNode;
  onClick: () => void;
  variant?: "primary" | "danger" | "ghost";
  icon?: string;
}

export function FBtn({
  children,
  onClick,
  variant = "ghost",
  icon,
}: FBtnProps) {
  const [hov, setHov] = useState(false);
  const { dark } = useTheme();
  const t = getTheme(dark);
  let bg: string, color: string, border: string, shadow: string;

  if (variant === "primary") {
    bg = hov ? BURG_LT : BURG;
    color = "#fff";
    border = "none";
    shadow = hov
      ? `0 4px 20px rgba(139,26,47,0.3)`
      : `0 2px 12px rgba(139,26,47,0.22)`;
  } else if (variant === "danger") {
    bg = hov ? "rgba(196,55,79,0.12)" : "transparent";
    color = BURG_LT;
    border = `1.5px solid rgba(196,55,79,0.3)`;
    shadow = "none";
  } else {
    bg = hov ? t.hover : "transparent";
    color = t.textSub;
    border = `1.5px solid ${t.border}`;
    shadow = "none";
  }

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: bg,
        color,
        border,
        borderRadius: 10,
        fontSize: 13,
        fontWeight: 600,
        padding: "10px 18px",
        cursor: "pointer",
        transition: "all 0.15s",
        boxShadow: shadow,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 7,
        whiteSpace: "nowrap",
      }}
    >
      {icon && <LIcon name={icon} size={14} color={color} />}
      {children}
    </button>
  );
}

interface PanelShellProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  icon?: string;
  /** Distance from the screen's true right edge — lets a second, narrower
   *  panel sit further right while this one shifts left to make room. */
  stackOffset?: number;
  /** Reports this panel's live width (initial + every drag-resize step) so
   *  a sibling panel can track it via `stackOffset`. */
  onWidthChange?: (w: number) => void;
}

const PANEL_MIN_WIDTH = 360;
const PANEL_MAX_WIDTH = 980;
const PANEL_DEFAULT_WIDTH = 360;

export function PanelShell({
  title,
  onClose,
  children,
  icon,
  stackOffset = 0,
  onWidthChange,
}: PanelShellProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [width, setWidth] = useState(PANEL_DEFAULT_WIDTH);
  const dragging = useRef(false);

  useEffect(() => {
    onWidthChange?.(width);
  }, [width, onWidthChange]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = window.innerWidth - e.clientX;
      setWidth(Math.min(PANEL_MAX_WIDTH, Math.max(PANEL_MIN_WIDTH, next)));
    };
    const stopDragging = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", stopDragging);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", stopDragging);
    };
  }, []);

  const startDragging = (e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: stackOffset,
        bottom: 0,
        width,
        display: "flex",
        alignItems: "stretch",
        padding: 16,
        zIndex: 200,
        pointerEvents: "none",
      }}
    >
      {/* Drag handle — straddles the panel's true left edge (not the padded
          content edge) so the width doesn't jump when the drag starts. Lets
          wide content (e.g. a full table preview) be viewed without
          horizontal scrolling. */}
      <div
        onMouseDown={startDragging}
        title="Drag to resize"
        style={{
          position: "absolute",
          left: -7,
          top: 0,
          bottom: 0,
          width: 14,
          cursor: "ew-resize",
          pointerEvents: "all",
          zIndex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: 4,
            height: 52,
            borderRadius: 4,
            background: t.borderHi,
            transition: "background 0.15s",
          }}
        />
      </div>
      <div
        style={{
          flex: 1,
          minWidth: 0,
          background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,253,255,0.98)",
          backdropFilter: "blur(32px)",
          borderRadius: 20,
          border: `1px solid ${t.borderHi}`,
          display: "flex",
          flexDirection: "column",
          pointerEvents: "all",
          boxShadow: dark
            ? "0 24px 80px rgba(0,0,0,0.75), 0 0 0 1px rgba(255,255,255,0.04)"
            : "0 24px 80px rgba(0,0,0,0.13)",
          animation: "panelSlide 0.24s cubic-bezier(0.22,1,0.36,1)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "18px 20px 14px",
            borderBottom: `1px solid ${t.border}`,
            flexShrink: 0,
          }}
        >
          {icon && (
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: 8,
                background: BURG_DIM,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <LIcon name={icon} size={15} color={BURG} />
            </div>
          )}
          <span
            style={{ fontWeight: 700, fontSize: 14, color: t.text, flex: 1 }}
          >
            {title}
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: t.textDim,
              padding: 6,
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color = t.text)
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color = t.textDim)
            }
          >
            <LIcon name="X" size={16} color="currentColor" />
          </button>
        </div>
        <div
          className="pscroll"
          style={{ flex: 1, overflowY: "auto", padding: "4px 20px 24px" }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
