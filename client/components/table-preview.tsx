"use client";

import { useMemo } from "react";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon } from "@/lib/icons";

export interface ParsedCsv {
  headers: string[];
  rows: string[][];
}

/** Naive CSV parse — fine for a preview grid; downloads use the raw text. */
export function parseCsv(text: string): ParsedCsv {
  const lines = text.trim().split(/\r?\n/);
  if (!lines.length) return { headers: [], rows: [] };
  const split = (line: string) => line.split(",");
  return { headers: split(lines[0]), rows: lines.slice(1).map(split) };
}

export function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const cellBase: React.CSSProperties = {
  padding: "7px 12px",
  fontSize: 12,
  fontFamily: "'JetBrains Mono', monospace",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
  maxWidth: 220,
};

/** Scrollable, zebra-striped grid. The final column is accented as the
 *  "prediction" column — the typical output of the tabular flow. */
function TableGrid({
  data,
  dark,
  maxRows,
  compact,
}: {
  data: ParsedCsv;
  dark: boolean;
  maxRows?: number;
  compact?: boolean;
}) {
  const t = getTheme(dark);
  const rows = maxRows ? data.rows.slice(0, maxRows) : data.rows;
  const last = data.headers.length - 1;
  const accent = (i: number): React.CSSProperties =>
    i === last && data.headers.length > 1
      ? { background: dark ? "rgba(139,26,47,0.14)" : "rgba(139,26,47,0.07)" }
      : {};

  return (
    <table style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead>
        <tr>
          {data.headers.map((h, i) => (
            <th
              key={i}
              style={{
                ...cellBase,
                ...accent(i),
                textAlign: "left",
                fontWeight: 700,
                color: i === last && last > 0 ? BURG_LT : t.text,
                background:
                  i === last && last > 0
                    ? dark
                      ? "rgba(139,26,47,0.2)"
                      : "rgba(139,26,47,0.1)"
                    : t.inputBg,
                borderBottom: `1.5px solid ${t.borderHi}`,
                position: "sticky",
                top: 0,
                zIndex: 1,
                fontSize: compact ? 11 : 12,
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, ri) => (
          <tr
            key={ri}
            style={{
              background:
                ri % 2
                  ? dark
                    ? "rgba(255,255,255,0.02)"
                    : "rgba(0,0,0,0.02)"
                  : "transparent",
            }}
          >
            {data.headers.map((_, ci) => (
              <td
                key={ci}
                style={{
                  ...cellBase,
                  ...accent(ci),
                  color:
                    ci === last && last > 0
                      ? dark
                        ? "#E08597"
                        : BURG
                      : t.textSub,
                  fontWeight: ci === last && last > 0 ? 700 : 400,
                  borderBottom: `1px solid ${t.border}`,
                  fontSize: compact ? 11 : 12,
                }}
              >
                {r[ci] ?? ""}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DownloadButton({ csv, filename }: { csv: string; filename: string }) {
  return (
    <button
      onClick={() => downloadCsv(csv, filename)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        background: BURG,
        border: "none",
        color: "#fff",
        borderRadius: 9,
        padding: "8px 14px",
        fontSize: 12,
        fontWeight: 700,
        cursor: "pointer",
        boxShadow: `0 2px 14px ${BURG_GLOW}`,
        transition: "background 0.15s",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = BURG_LT;
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = BURG;
      }}
    >
      <LIcon name="Download" size={14} color="currentColor" />
      Download CSV
    </button>
  );
}

/** Full-screen overview popup for an exported table, with a download button
 *  in the corner. */
export function TablePreviewModal({
  csv,
  title = "Result table",
  filename = "table-result.csv",
  onClose,
}: {
  csv: string;
  title?: string;
  filename?: string;
  onClose: () => void;
}) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const data = useMemo(() => parseCsv(csv), [csv]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 600,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: dark ? "rgba(0,0,0,0.68)" : "rgba(220,216,235,0.62)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        animation: "fadeIn 0.2s ease-out",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: "min(920px, 94vw)",
          maxHeight: "86vh",
          background: dark ? "rgba(8,6,16,0.98)" : "rgba(255,254,255,0.99)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 16,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: dark
            ? "0 24px 80px rgba(0,0,0,0.72), 0 0 0 1px rgba(139,26,47,0.22)"
            : "0 24px 80px rgba(0,0,0,0.18), 0 0 0 1px rgba(139,26,47,0.14)",
          animation: "logSlide 0.28s cubic-bezier(0.22,1,0.36,1)",
        }}
      >
        {/* Header with download in the corner */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            padding: "16px 18px",
            borderBottom: `1px solid ${t.border}`,
            flexShrink: 0,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 11,
              minWidth: 0,
            }}
          >
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 9,
                background: dark
                  ? "rgba(139,26,47,0.2)"
                  : "rgba(139,26,47,0.1)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <LIcon name="Table2" size={18} color={BURG_LT} />
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
                {title}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: t.textDim,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {data.rows.length} row{data.rows.length === 1 ? "" : "s"} ×{" "}
                {data.headers.length} column
                {data.headers.length === 1 ? "" : "s"}
              </div>
            </div>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexShrink: 0,
            }}
          >
            <DownloadButton csv={csv} filename={filename} />
            <button
              onClick={onClose}
              title="Close"
              style={{
                background: "none",
                border: `1px solid ${t.border}`,
                cursor: "pointer",
                color: t.textDim,
                display: "flex",
                padding: 7,
                borderRadius: 8,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.color = t.text;
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.color = t.textDim;
              }}
            >
              <LIcon name="X" size={15} color="currentColor" />
            </button>
          </div>
        </div>

        {/* Scrollable grid */}
        <div style={{ overflow: "auto", padding: "0 2px" }}>
          <TableGrid data={data} dark={dark} />
        </div>
      </div>
    </div>
  );
}

/** Pinned headline banner: a run that produced a table treats the table as its
 *  primary result (not a Q&A text answer). Shown at the top of the activity log. */
export function ResultBanner({
  csv,
  onOpen,
  dark,
}: {
  csv: string;
  onOpen: () => void;
  dark: boolean;
}) {
  const t = getTheme(dark);
  const data = useMemo(() => parseCsv(csv), [csv]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 11,
        margin: "10px 12px 4px",
        padding: "11px 13px",
        borderRadius: 12,
        border: `1px solid ${t.borderHi}`,
        background: dark
          ? "linear-gradient(135deg, rgba(139,26,47,0.22), rgba(139,26,47,0.08))"
          : "linear-gradient(135deg, rgba(139,26,47,0.1), rgba(139,26,47,0.03))",
        boxShadow: `0 2px 16px ${BURG_GLOW}`,
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 9,
          background: dark ? "rgba(139,26,47,0.28)" : "rgba(139,26,47,0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <LIcon name="Table2" size={17} color={BURG_LT} />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text }}>
          Result table ready
        </div>
        <div
          style={{
            fontSize: 10,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {data.rows.length} row{data.rows.length === 1 ? "" : "s"} ×{" "}
          {data.headers.length} column{data.headers.length === 1 ? "" : "s"}
        </div>
      </div>
      <button
        onClick={onOpen}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          background: BURG,
          border: "none",
          color: "#fff",
          borderRadius: 8,
          padding: "7px 12px",
          fontSize: 11,
          fontWeight: 700,
          cursor: "pointer",
          flexShrink: 0,
          boxShadow: `0 2px 12px ${BURG_GLOW}`,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = BURG_LT;
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = BURG;
        }}
      >
        <LIcon name="Maximize2" size={11} color="currentColor" />
        Preview
      </button>
      <button
        onClick={() => downloadCsv(csv, "table-result.csv")}
        title="Download CSV"
        style={{
          display: "inline-flex",
          alignItems: "center",
          background: "none",
          border: `1px solid ${t.borderHi}`,
          color: t.textSub,
          borderRadius: 8,
          padding: 7,
          cursor: "pointer",
          flexShrink: 0,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = t.text;
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = t.textSub;
        }}
      >
        <LIcon name="Download" size={13} color="currentColor" />
      </button>
    </div>
  );
}

/** Compact inline card shown in the activity log when a table is exported. */
export function TableResultCard({
  csv,
  onOpen,
  dark,
}: {
  csv: string;
  onOpen: () => void;
  dark: boolean;
}) {
  const t = getTheme(dark);
  const data = useMemo(() => parseCsv(csv), [csv]);

  return (
    <div
      style={{
        marginTop: 6,
        border: `1px solid ${t.borderHi}`,
        borderRadius: 11,
        overflow: "hidden",
        background: dark ? "rgba(139,26,47,0.06)" : "rgba(139,26,47,0.035)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 11px",
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        <LIcon name="Table2" size={13} color={BURG_LT} />
        <span style={{ fontSize: 11, fontWeight: 700, color: t.text }}>
          Result table
        </span>
        <span
          style={{
            fontSize: 9.5,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {data.rows.length}×{data.headers.length}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button
            onClick={onOpen}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              background: BURG,
              border: "none",
              color: "#fff",
              borderRadius: 7,
              padding: "4px 9px",
              fontSize: 10,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            <LIcon name="Maximize2" size={10} color="currentColor" />
            Preview
          </button>
        </div>
      </div>
      <div style={{ overflow: "auto", maxHeight: 132 }}>
        <TableGrid data={data} dark={dark} maxRows={4} compact />
      </div>
      {data.rows.length > 4 && (
        <div
          style={{
            padding: "4px 11px",
            fontSize: 9.5,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          +{data.rows.length - 4} more rows — open preview to see all & download
        </div>
      )}
    </div>
  );
}
