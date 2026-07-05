"use client";

import { ContractInfo, ThreadInfo } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG, BURG_LT } from "@/lib/theme";

interface ContractDocumentProps {
  contract: ContractInfo;
  /** The threads the contract was decomposed into — the Schedule of Work. */
  threads: ThreadInfo[];
}

const SERIF = "'Playfair Display', Georgia, serif";
const SANS = "'Space Grotesk', system-ui, sans-serif";
const MONO = "'JetBrains Mono', monospace";

/** Turn a snake/kebab machine task type ("energy_contract_review") into a
 *  human title ("Energy Contract Review"). */
export function humanizeTaskType(raw: string): string {
  const words = raw.replace(/[_-]+/g, " ").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "Task";
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Circular stamp carrying the Market Maker's scoping confidence — the one
 *  deliberately document-flavoured flourish left on the contract. */
function ConfidenceSeal({ pct, ink }: { pct: number; ink: string }) {
  return (
    <svg
      width={70}
      height={70}
      viewBox="0 0 76 76"
      style={{ transform: "rotate(-8deg)", flexShrink: 0, opacity: 0.85 }}
      aria-label={`Market Maker seal — ${pct}% scoping confidence`}
    >
      <defs>
        <path id="seal-arc-top" d="M 12 38 A 26 26 0 0 1 64 38" />
        <path id="seal-arc-bottom" d="M 12 38 A 26 26 0 0 0 64 38" />
      </defs>
      <circle
        cx={38}
        cy={38}
        r={35}
        fill="none"
        stroke={ink}
        strokeWidth={1.6}
      />
      <circle
        cx={38}
        cy={38}
        r={31.5}
        fill="none"
        stroke={ink}
        strokeWidth={0.6}
      />
      <text
        fontSize={6.4}
        fontWeight={700}
        letterSpacing={1.6}
        fill={ink}
        fontFamily={SANS}
      >
        <textPath href="#seal-arc-top" startOffset="50%" textAnchor="middle">
          MARKET MAKER
        </textPath>
      </text>
      <text
        fontSize={6.4}
        fontWeight={700}
        letterSpacing={1.6}
        fill={ink}
        fontFamily={SANS}
      >
        <textPath href="#seal-arc-bottom" startOffset="50%" textAnchor="middle">
          · SCOPED ·
        </textPath>
      </text>
      <text
        x={38}
        y={41}
        textAnchor="middle"
        fontSize={15}
        fontWeight={700}
        fill={ink}
        fontFamily={SERIF}
      >
        {pct}%
      </text>
      <text
        x={38}
        y={50}
        textAnchor="middle"
        fontSize={4.6}
        letterSpacing={1.1}
        fontWeight={600}
        fill={ink}
        fontFamily={SANS}
      >
        CONFIDENCE
      </text>
    </svg>
  );
}

/**
 * The Market Maker's contract — a light document feel (title, schedule of
 * work, confidence seal) dressed in the app's own burgundy/glass language
 * rather than parchment formality. Pure presentation: shared between the
 * Draft board's inline card and the dock's popup reveal.
 */
export function ContractDocument({ contract, threads }: ContractDocumentProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const hairline = dark ? "rgba(196,55,79,0.2)" : "rgba(139,26,47,0.14)";
  const rule = dark ? "rgba(196,55,79,0.4)" : "rgba(139,26,47,0.32)";
  const sealInk = dark ? BURG_LT : BURG;

  const title = humanizeTaskType(contract.task_type);
  const pct = Math.round(Math.max(0, Math.min(1, contract.confidence)) * 100);
  const isMulti = contract.task_nature === "multi";
  const expertise = contract.required_expertise ?? [];
  const contractNo = contract.id.replace(/-/g, "").slice(0, 8).toUpperCase();

  const sectionLabel: React.CSSProperties = {
    fontSize: 9,
    fontWeight: 800,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    color: BURG_LT,
    fontFamily: SANS,
    marginBottom: 6,
  };

  return (
    <div
      style={{
        padding: "16px 16px 14px",
        borderTop: `1px solid ${hairline}`,
        fontFamily: SANS,
        color: t.textSub,
      }}
    >
      {/* ── Heading ── */}
      <div style={{ textAlign: "center", marginBottom: 14 }}>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            fontFamily: SERIF,
            color: t.text,
            lineHeight: 1.25,
          }}
        >
          {title}
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: 14,
            marginTop: 6,
            fontSize: 9,
            fontFamily: MONO,
            color: t.textDim,
            letterSpacing: "0.04em",
          }}
        >
          <span>N° {contractNo}</span>
          <span>·</span>
          <span>{formatDate(contract.created_at)}</span>
        </div>
      </div>

      {/* ── Scope — the user's ask, quoted ── */}
      {contract.original_prompt?.trim() && (
        <div style={{ marginBottom: 13 }}>
          <div style={sectionLabel}>Scope</div>
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.6,
              fontStyle: "italic",
              color: t.textSub,
              paddingLeft: 10,
              borderLeft: `2px solid ${rule}`,
            }}
          >
            “{contract.original_prompt.trim()}”
          </div>
        </div>
      )}

      {/* ── Shape — how the Market Maker read the job ── */}
      <div style={{ marginBottom: 13 }}>
        <div style={sectionLabel}>Shape of the work</div>
        <div style={{ fontSize: 12, lineHeight: 1.65 }}>
          Scoped as{" "}
          <strong style={{ color: t.text, fontWeight: 700 }}>
            {title.toLowerCase()}
          </strong>{" "}
          of{" "}
          <strong style={{ color: t.text, fontWeight: 700 }}>
            {contract.complexity}
          </strong>{" "}
          complexity —{" "}
          {isMulti
            ? `split into ${threads.length || "multiple"} parallel workstream${
                threads.length === 1 ? "" : "s"
              }`
            : "a single workstream"}
          .
        </div>
      </div>

      {/* ── Required expertise ── */}
      {expertise.length > 0 && (
        <div style={{ marginBottom: 13 }}>
          <div style={sectionLabel}>Required expertise</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {expertise.map((skill) => (
              <span
                key={skill}
                style={{
                  padding: "3px 9px",
                  borderRadius: 999,
                  fontSize: 10.5,
                  fontWeight: 600,
                  color: dark ? "rgba(255,240,242,0.92)" : BURG,
                  background: dark
                    ? "rgba(139,26,47,0.2)"
                    : "rgba(139,26,47,0.07)",
                  border: "1px solid rgba(139,26,47,0.26)",
                  textTransform: "capitalize",
                }}
              >
                {skill.replace(/[_-]+/g, " ")}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Schedule of work — the threads ── */}
      {threads.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={sectionLabel}>Schedule of work</div>
          {threads.map((th, i) => (
            <div
              key={th.id}
              style={{
                display: "flex",
                gap: 10,
                padding: "8px 0",
                borderTop: i > 0 ? `1px solid ${hairline}` : "none",
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  fontFamily: MONO,
                  color: BURG_LT,
                  flexShrink: 0,
                  paddingTop: 2,
                }}
              >
                {String(i + 1).padStart(2, "0")}
              </div>
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 12.5,
                    fontWeight: 700,
                    color: t.text,
                    lineHeight: 1.35,
                  }}
                >
                  {th.title}
                </div>
                {th.description?.trim() && (
                  <div
                    style={{
                      fontSize: 11.5,
                      lineHeight: 1.55,
                      color: t.textSub,
                      marginTop: 2,
                    }}
                  >
                    {th.description}
                  </div>
                )}
                <div
                  style={{
                    fontSize: 8.5,
                    marginTop: 4,
                    letterSpacing: "0.09em",
                    textTransform: "uppercase",
                    color: t.textDim,
                    fontWeight: 600,
                  }}
                >
                  {th.required_expertise.length > 0 && (
                    <>
                      {th.required_expertise.join(" · ").replace(/[_-]+/g, " ")}
                      {"  —  "}
                    </>
                  )}
                  {th.complexity} complexity
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Sign-off ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${hairline}`,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 15,
              fontStyle: "italic",
              fontWeight: 700,
              fontFamily: SERIF,
              color: t.text,
              transform: "rotate(-2deg)",
              whiteSpace: "nowrap",
            }}
          >
            The Market Maker
          </div>
          <div
            style={{
              marginTop: 3,
              fontSize: 8,
              fontWeight: 700,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: t.textDim,
            }}
          >
            Drafted &amp; scoped
          </div>
        </div>
        <ConfidenceSeal pct={pct} ink={sealInk} />
      </div>
    </div>
  );
}
