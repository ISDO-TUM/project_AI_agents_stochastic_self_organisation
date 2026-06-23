"use client";

import { LIcon } from "@/lib/icons";
import { BURG, BURG_DIM, getTheme } from "@/lib/theme";

export const MONO = "'JetBrains Mono', monospace";

export const CHART_COLORS = [
  "#8b1a2f",
  "#5a8bce",
  "#6ec1a8",
  "#d8b15a",
  "#9b7bce",
  "#c2596d",
  "#bf6f45",
  "#5d697c",
];

export const ENTRANCE = "statCardIn 0.5s cubic-bezier(0.22,1,0.36,1) both";

export function cardSurface(dark: boolean): React.CSSProperties {
  const t = getTheme(dark);
  return {
    background: dark ? "rgba(13,11,22,0.78)" : "rgba(255,255,255,0.82)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    border: `1px solid ${t.border}`,
    borderRadius: 14,
    boxShadow: dark
      ? "0 10px 36px rgba(0,0,0,0.35)"
      : "0 8px 28px rgba(24,22,31,0.06)",
  };
}

export function labelStyle(dark: boolean): React.CSSProperties {
  return {
    color: getTheme(dark).textDim,
    fontFamily: MONO,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 1.3,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  };
}

export function chartTooltipProps(dark: boolean) {
  const t = getTheme(dark);
  return {
    contentStyle: {
      background: dark ? "rgba(10,8,18,0.96)" : "rgba(255,254,255,0.98)",
      border: `1px solid ${t.borderHi}`,
      borderRadius: 10,
      boxShadow: dark
        ? "0 8px 32px rgba(0,0,0,0.55)"
        : "0 8px 24px rgba(0,0,0,0.12)",
      color: t.text,
      fontSize: 12,
      padding: "8px 12px",
    } as React.CSSProperties,
    labelStyle: {
      color: t.text,
      fontWeight: 700,
      marginBottom: 4,
    } as React.CSSProperties,
    itemStyle: { padding: "1px 0" } as React.CSSProperties,
  };
}

export function StatCard({
  title,
  icon,
  meta,
  children,
  dark,
  delay = 0,
  minHeight,
}: {
  title: string;
  icon: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
  dark: boolean;
  delay?: number;
  minHeight?: number;
}) {
  const t = getTheme(dark);
  return (
    <section
      style={{
        ...cardSurface(dark),
        padding: "16px 18px",
        minHeight,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        animation: ENTRANCE,
        animationDelay: `${delay}ms`,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 9,
          marginBottom: 14,
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: 7,
            background: BURG_DIM,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <LIcon name={icon} size={13} color={BURG} />
        </div>
        <span style={{ ...labelStyle(dark), color: t.textSub }}>{title}</span>
        {meta != null && <div style={{ marginLeft: "auto" }}>{meta}</div>}
      </header>
      <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>{children}</div>
    </section>
  );
}

export function Kpi({
  label,
  value,
  icon,
  dark,
  delay = 0,
  variant = "number",
}: {
  label: string;
  value: React.ReactNode;
  icon?: string;
  dark: boolean;
  delay?: number;
  // "number" shows the big metric figure; "text" is for string values
  // (e.g. a model name) that would otherwise overflow the card.
  variant?: "number" | "text";
}) {
  const t = getTheme(dark);
  const isText = variant === "text";
  return (
    <div
      style={{
        ...cardSurface(dark),
        borderRadius: 12,
        padding: "13px 15px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minWidth: 0,
        animation: ENTRANCE,
        animationDelay: `${delay}ms`,
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
        <span style={labelStyle(dark)}>{label}</span>
        {icon && <LIcon name={icon} size={13} color={t.textDim} />}
      </div>
      <div
        title={isText && typeof value === "string" ? value : undefined}
        style={{
          color: t.text,
          fontSize: isText ? 15 : 24,
          fontWeight: isText ? 650 : 700,
          letterSpacing: isText ? 0 : -0.4,
          lineHeight: isText ? 1.35 : 1.15,
          overflowWrap: "anywhere",
          ...(isText
            ? {
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }
            : null),
        }}
      >
        {value}
      </div>
    </div>
  );
}

export function StatusBadge({
  status,
  dark,
}: {
  status: string;
  dark: boolean;
}) {
  const s = status.toLowerCase();
  let color: string;
  if (
    s.includes("complet") ||
    s.includes("success") ||
    s.includes("done") ||
    s.includes("converg")
  ) {
    color = dark ? "#6ec1a8" : "#2f8f6f";
  } else if (
    s.includes("run") ||
    s.includes("progress") ||
    s.includes("pend") ||
    s.includes("active")
  ) {
    color = dark ? "#d8b15a" : "#9a7b2e";
  } else if (
    s.includes("fail") ||
    s.includes("err") ||
    s.includes("cancel") ||
    s.includes("abort")
  ) {
    color = dark ? "#c4374f" : "#8b1a2f";
  } else {
    color = getTheme(dark).textSub;
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 100,
        background: `${color}1f`,
        border: `1px solid ${color}38`,
        color,
        fontSize: 11,
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          boxShadow: `0 0 6px ${color}`,
          flexShrink: 0,
        }}
      />
      {status}
    </span>
  );
}

export function MetaChip({
  icon,
  children,
  dark,
}: {
  icon: string;
  children: React.ReactNode;
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 100,
        background: t.inputBg,
        border: `1px solid ${t.border}`,
        color: t.textSub,
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      <LIcon name={icon} size={12} color="currentColor" />
      {children}
    </span>
  );
}

export function ChartLegend({
  items,
  dark,
}: {
  items: { label: string; color: string }[];
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      {items.map((item) => (
        <span
          key={item.label}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            fontSize: 11,
            fontWeight: 600,
            color: t.textSub,
            whiteSpace: "nowrap",
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: item.color,
              boxShadow: `0 0 6px ${item.color}55`,
              flexShrink: 0,
            }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  sub,
  action,
  dark,
  delay = 0,
}: {
  icon: string;
  title: string;
  sub?: string;
  action?: React.ReactNode;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  return (
    <div
      style={{
        ...cardSurface(dark),
        padding: "56px 28px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        textAlign: "center",
        gap: 8,
        animation: ENTRANCE,
        animationDelay: `${delay}ms`,
      }}
    >
      <div
        style={{
          width: 52,
          height: 52,
          borderRadius: 14,
          background: BURG_DIM,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 6,
          animation: "emptyFloat 4s ease-in-out infinite",
        }}
      >
        <LIcon name={icon} size={24} color={BURG} />
      </div>
      <div style={{ color: t.text, fontSize: 15, fontWeight: 700 }}>
        {title}
      </div>
      {sub && (
        <div
          style={{
            color: t.textSub,
            fontSize: 12.5,
            lineHeight: 1.6,
            maxWidth: 400,
          }}
        >
          {sub}
        </div>
      )}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  );
}

export function ErrorState({
  message,
  dark,
}: {
  message: string;
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <div
      style={{
        ...cardSurface(dark),
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "16px 18px",
        animation: ENTRANCE,
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 9,
          background: BURG_DIM,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <LIcon name="TriangleAlert" size={16} color={BURG} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ color: t.text, fontSize: 13, fontWeight: 700 }}>
          Could not load statistics
        </div>
        <div style={{ color: t.textSub, fontSize: 12, marginTop: 2 }}>
          {message}
        </div>
      </div>
    </div>
  );
}

export function SkeletonCard({
  height,
  dark,
  delay = 0,
  radius = 14,
}: {
  height: number;
  dark: boolean;
  delay?: number;
  radius?: number;
}) {
  const base = dark ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.045)";
  const sheen = dark ? "rgba(255,255,255,0.06)" : "rgba(255,255,255,0.65)";
  const t = getTheme(dark);
  return (
    <div
      style={{
        height,
        borderRadius: radius,
        border: `1px solid ${t.border}`,
        backgroundColor: base,
        backgroundImage: `linear-gradient(90deg, transparent, ${sheen}, transparent)`,
        backgroundSize: "600px 100%",
        backgroundRepeat: "no-repeat",
        animation: `shimmer 1.4s linear infinite, ${ENTRANCE}`,
        animationDelay: `0ms, ${delay}ms`,
      }}
    />
  );
}
