"use client";

import {
  useRef,
  useState,
  useCallback,
  useEffect,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

interface ToolbarProps {
  simMode: boolean;
  onToggleTheme: () => void;
  onAddAgent: () => void;
  onAddFile: () => void;
  onAddDataset: () => void;
  onClear: () => void;
  onStop: () => void;
  onAutoLayout: () => void;
  onExport: () => void;
  onImport: (raw: string) => void;
  onOpenHistory: () => void;
  showTweaks: boolean;
  onToggleTweaks: () => void;
  showBiddingBoardToggle?: boolean;
  biddingBoardOpen?: boolean;
  onToggleBiddingBoard?: () => void;
  onWidthChange?: (w: number) => void;
  onHeightChange?: (h: number) => void;
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

function ToolsMenuItem({
  icon,
  label,
  onClick,
  t,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  t: ReturnType<typeof getTheme>;
}) {
  return (
    <button
      onClick={onClick}
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
        (e.currentTarget as HTMLButtonElement).style.background = t.hover;
        (e.currentTarget as HTMLButtonElement).style.color = t.text;
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = "none";
        (e.currentTarget as HTMLButtonElement).style.color = t.textSub;
      }}
    >
      <LIcon name={icon} size={13} color="currentColor" />
      {label}
    </button>
  );
}

function ToolsDropdown({
  onAddFile,
  onAddDataset,
  t,
}: {
  onAddFile: () => void;
  onAddDataset: () => void;
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
            <ToolsMenuItem
              icon="FileText"
              label="Files"
              onClick={() => {
                setOpen(false);
                onAddFile();
              }}
              t={t}
            />
            <ToolsMenuItem
              icon="Table2"
              label="Dataset"
              onClick={() => {
                setOpen(false);
                onAddDataset();
              }}
              t={t}
            />
          </div>
        </>
      )}
    </div>
  );
}

// ── helpers ────────────────────────────────────────────────────────────────

function highlightJson(raw: string, dark: boolean): string {
  const c = dark
    ? {
        key: "#ff7b8a",
        str: "#98c379",
        num: "#79b8ff",
        kw: "#c678dd",
        def: "#abb2bf",
      }
    : {
        key: "#c0392b",
        str: "#27ae60",
        num: "#2471a3",
        kw: "#8e44ad",
        def: "#555",
      };

  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const re =
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = re.exec(raw)) !== null) {
    out += esc(raw.slice(last, m.index));
    last = re.lastIndex;
    const [, str, colon, kw, num] = m;
    if (str !== undefined) {
      const color = colon !== undefined ? c.key : c.str;
      out += `<span style="color:${color}">${esc(str)}</span>${
        colon ? esc(colon) : ""
      }`;
    } else if (kw !== undefined) {
      out += `<span style="color:${c.kw}">${kw}</span>`;
    } else if (num !== undefined) {
      out += `<span style="color:${c.num}">${num}</span>`;
    }
  }
  out += esc(raw.slice(last));
  return out;
}

function validateCanvas(parsed: unknown): string | null {
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
    return "Root must be a JSON object.";

  const obj = parsed as Record<string, unknown>;
  if (!Array.isArray(obj.agents)) return "Missing or invalid 'agents' array.";
  if (!Array.isArray(obj.sources)) return "Missing or invalid 'sources' array.";
  if (!Array.isArray(obj.edges)) return "Missing or invalid 'edges' array.";

  const SOURCE_TYPES = new Set(["text", "document", "dataset"]);

  for (let i = 0; i < (obj.agents as unknown[]).length; i++) {
    const a = (obj.agents as Record<string, unknown>[])[i];
    if (!a || typeof a !== "object") return `agents[${i}] is not an object.`;
    if (typeof a.id !== "string" || !a.id)
      return `agents[${i}]: 'id' must be a non-empty string.`;
    if (typeof a.name !== "string" || !a.name)
      return `agents[${i}]: 'name' must be a non-empty string.`;
    if (typeof a.provider !== "string" || !a.provider)
      return `agents[${i}] "${a.name}": missing 'provider'.`;
    if (typeof a.model !== "string" || !a.model)
      return `agents[${i}] "${a.name}": missing 'model'.`;
    if (!Array.isArray(a.tools))
      return `agents[${i}] "${a.name}": 'tools' must be an array.`;
    if (!Array.isArray(a.connections))
      return `agents[${i}] "${a.name}": 'connections' must be an array.`;
    const pos = a.position as Record<string, unknown>;
    if (!pos || typeof pos.x !== "number" || typeof pos.y !== "number")
      return `agents[${i}] "${a.name}": 'position' must have numeric x and y.`;
  }

  for (let i = 0; i < (obj.sources as unknown[]).length; i++) {
    const s = (obj.sources as Record<string, unknown>[])[i];
    if (!s || typeof s !== "object") return `sources[${i}] is not an object.`;
    if (typeof s.id !== "string" || !s.id)
      return `sources[${i}]: 'id' must be a non-empty string.`;
    if (typeof s.name !== "string" || !s.name)
      return `sources[${i}]: 'name' must be a non-empty string.`;
    if (!SOURCE_TYPES.has(s.type as string))
      return `sources[${i}] "${s.name}": 'type' must be "text", "document", or "dataset".`;
    if (typeof s.content !== "string")
      return `sources[${i}] "${s.name}": 'content' must be a string.`;
  }

  for (let i = 0; i < (obj.edges as unknown[]).length; i++) {
    const e = (obj.edges as Record<string, unknown>[])[i];
    if (!e || typeof e !== "object") return `edges[${i}] is not an object.`;
    if (typeof e.id !== "string") return `edges[${i}]: missing 'id'.`;
    if (typeof e.from !== "string") return `edges[${i}]: missing 'from'.`;
    if (typeof e.to !== "string") return `edges[${i}]: missing 'to'.`;
  }

  return null;
}

// ── toast ──────────────────────────────────────────────────────────────────

function ImportToast({
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

// ── modal ──────────────────────────────────────────────────────────────────

const EDITOR_FONT = "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace";
const EDITOR_SIZE = 12.5;
const EDITOR_LH = 1.65;
const EDITOR_PAD = "14px 16px";

function JsonPasteModal({
  onImport,
  onClose,
  t,
  dark,
}: {
  onImport: (raw: string) => void;
  onClose: () => void;
  t: ReturnType<typeof getTheme>;
  dark: boolean;
}) {
  const [value, setValue] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  // createPortal needs `document`, which doesn't exist during SSR — render
  // null on the server snapshot and the portal once mounted on the client.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const preRef = useRef<HTMLPreElement>(null);

  const tryFormat = useCallback((raw: string) => {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }, []);

  const handlePaste = () => {
    setTimeout(() => setValue((v) => tryFormat(v)), 0);
  };

  const syncScroll = (el: HTMLTextAreaElement) => {
    if (preRef.current) {
      preRef.current.scrollTop = el.scrollTop;
      preRef.current.scrollLeft = el.scrollLeft;
    }
  };

  const handleImport = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(value);
    } catch {
      setToast("Invalid JSON — check your syntax.");
      return;
    }
    const err = validateCanvas(parsed);
    if (err) {
      setToast(err);
      return;
    }
    onImport(value);
    onClose();
  };

  const highlighted = highlightJson(value, dark);

  const btnBase: React.CSSProperties = {
    border: "none",
    borderRadius: 9,
    padding: "9px 18px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    transition: "all 0.15s",
  };

  const editorShared: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    margin: 0,
    padding: EDITOR_PAD,
    fontFamily: EDITOR_FONT,
    fontSize: EDITOR_SIZE,
    lineHeight: EDITOR_LH,
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
    tabSize: 2,
  };

  if (!mounted) return null;

  return createPortal(
    <>
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 200,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backdropFilter: "blur(2px)",
          background: dark ? "rgba(6,5,12,0.65)" : "rgba(240,238,248,0.65)",
        }}
        onClick={onClose}
      >
        <div
          style={{
            background: dark ? "rgba(12,10,22,0.97)" : "rgba(255,254,255,0.98)",
            border: `1px solid ${t.borderHi}`,
            borderRadius: 14,
            padding: 24,
            width: "min(660px, 92vw)",
            boxShadow: dark
              ? "0 20px 60px rgba(0,0,0,0.6)"
              : "0 12px 40px rgba(0,0,0,0.15)",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 15, color: t.text }}>
              Import JSON
            </span>
            <button
              onClick={onClose}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: t.textSub,
                display: "flex",
                padding: 4,
                borderRadius: 6,
              }}
            >
              <LIcon name="X" size={16} color="currentColor" />
            </button>
          </div>

          {/* highlighted editor */}
          <div
            style={{
              position: "relative",
              height: 360,
              borderRadius: 10,
              border: `1.5px solid ${t.border}`,
              background: t.inputBg,
              overflow: "hidden",
            }}
          >
            {/* highlighted display layer */}
            <pre
              ref={preRef}
              aria-hidden
              style={{
                ...editorShared,
                color: t.text,
                background: "transparent",
                overflow: "hidden",
                pointerEvents: "none",
                userSelect: "none",
              }}
              dangerouslySetInnerHTML={{
                __html: value
                  ? highlighted
                  : `<span style="color:${t.textDim}">Paste your canvas JSON here…</span>`,
              }}
            />

            {/* input layer */}
            <textarea
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onPaste={handlePaste}
              onScroll={(e) => syncScroll(e.currentTarget)}
              spellCheck={false}
              autoComplete="off"
              style={{
                ...editorShared,
                position: "absolute",
                color: "transparent",
                caretColor: t.text,
                background: "transparent",
                border: "none",
                outline: "none",
                resize: "none",
                overflow: "auto",
                zIndex: 1,
              }}
            />
          </div>

          {/* actions */}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <button
              onClick={onClose}
              style={{
                ...btnBase,
                background: t.inputBg,
                color: t.textSub,
                border: `1.5px solid ${t.border}`,
              }}
            >
              Cancel
            </button>
            <button
              onClick={handleImport}
              style={{ ...btnBase, background: BURG, color: "#fff" }}
              onMouseEnter={(e) =>
                ((e.currentTarget as HTMLButtonElement).style.background =
                  BURG_LT)
              }
              onMouseLeave={(e) =>
                ((e.currentTarget as HTMLButtonElement).style.background = BURG)
              }
            >
              Import
            </button>
          </div>
        </div>
      </div>

      {toast && <ImportToast message={toast} onDone={() => setToast(null)} />}
    </>,
    document.body,
  );
}

function ImportDropdown({
  onImport,
  t,
}: {
  onImport: (raw: string) => void;
  t: ReturnType<typeof getTheme>;
}) {
  const [open, setOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const { dark } = useTheme();

  return (
    <>
      <div style={{ position: "relative" }}>
        <TBtn
          onClick={() => setOpen((x) => !x)}
          icon="Upload"
          title="Import"
          active={open}
          t={t}
        >
          Import
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
                minWidth: 170,
                zIndex: 99,
                boxShadow: dark
                  ? "0 8px 32px rgba(0,0,0,0.55)"
                  : "0 8px 24px rgba(0,0,0,0.12)",
                animation: "fadeIn 0.15s ease-out",
              }}
            >
              <ToolsMenuItem
                icon="FolderOpen"
                label="Choose from files"
                onClick={() => {
                  setOpen(false);
                  fileRef.current?.click();
                }}
                t={t}
              />
              <ToolsMenuItem
                icon="Clipboard"
                label="Paste JSON"
                onClick={() => {
                  setOpen(false);
                  setPasteOpen(true);
                }}
                t={t}
              />
            </div>
          </>
        )}

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
      </div>

      {pasteOpen && (
        <JsonPasteModal
          onImport={onImport}
          onClose={() => setPasteOpen(false)}
          t={t}
          dark={dark}
        />
      )}
    </>
  );
}

function TLink({
  children,
  href,
  icon,
  title,
  t,
}: {
  children: React.ReactNode;
  href: string;
  icon?: string;
  title?: string;
  t: ReturnType<typeof getTheme>;
}) {
  const [hov, setHov] = useState(false);
  return (
    <Link
      href={href}
      title={title}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: hov ? t.hover : "transparent",
        borderRadius: 8,
        color: hov ? t.text : t.textSub,
        fontSize: 12,
        fontWeight: 600,
        padding: "6px 11px",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 6,
        transition: "all 0.15s",
        whiteSpace: "nowrap",
        textDecoration: "none",
      }}
    >
      {icon && <LIcon name={icon} size={14} color="currentColor" />}
      {children}
    </Link>
  );
}

export function Toolbar({
  simMode,
  onToggleTheme,
  onAddAgent,
  onAddFile,
  onAddDataset,
  onClear,
  onStop,
  onAutoLayout,
  onExport,
  onImport,
  onOpenHistory,
  showTweaks,
  onToggleTweaks,
  showBiddingBoardToggle,
  biddingBoardOpen,
  onToggleBiddingBoard,
  onWidthChange,
  onHeightChange,
}: ToolbarProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const pillRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = pillRef.current;
    if (!el || (!onWidthChange && !onHeightChange)) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      if (rect.width) onWidthChange?.(rect.width);
      if (rect.height) onHeightChange?.(rect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [onWidthChange, onHeightChange]);

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
      <div ref={pillRef} style={pillStyle}>
        {/* Logo */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            paddingRight: 6,
            flexShrink: 0,
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={dark ? "/logo_dark.png" : "/logo_light.png"}
            alt="logo"
            style={{
              height: 22,
              width: "auto",
              display: "block",
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontWeight: 700,
              fontSize: 12,
              color: t.text,
              letterSpacing: 0.2,
              fontFamily: "var(--font-space-grotesk), system-ui",
              whiteSpace: "nowrap",
            }}
          >
            Mycellium
          </span>
        </div>

        <Sep t={t} />

        {!simMode && (
          <>
            <TBtn onClick={onAddAgent} icon="Plus" title="Add Agent" t={t}>
              Agent
            </TBtn>
            <ToolsDropdown
              onAddFile={onAddFile}
              onAddDataset={onAddDataset}
              t={t}
            />
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
            <ImportDropdown onImport={onImport} t={t} />
            <TBtn
              onClick={onOpenHistory}
              icon="Database"
              title="Simulation history"
              t={t}
            >
              History
            </TBtn>
            <TLink
              href="/statistics"
              icon="ChartNoAxesColumn"
              title="Statistics"
              t={t}
            >
              Stats
            </TLink>
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

        {simMode && showBiddingBoardToggle && onToggleBiddingBoard && (
          <TBtn
            onClick={onToggleBiddingBoard}
            icon="ClipboardList"
            title="Bidding board"
            active={biddingBoardOpen}
            t={t}
          >
            Board
          </TBtn>
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
            marginRight: 6,
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
