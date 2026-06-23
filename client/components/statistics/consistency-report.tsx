"use client";

import {
  ENTRANCE,
  MONO,
  StatCard,
  cardSurface,
  labelStyle,
} from "@/components/statistics/primitives";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_DIM, getTheme } from "@/lib/theme";
import type { ConsistencyReport } from "@/lib/types";

function similarityColor(score: number): string {
  if (score >= 0.85) return "#4ade80"; // green
  if (score >= 0.6) return "#facc15"; // amber
  return "#f87171"; // red
}

function similarityLabel(score: number): string {
  if (score >= 0.85) return "High";
  if (score >= 0.6) return "Moderate";
  return "Low";
}

export function ConsistencySection({
  report,
  dark,
  delay = 0,
}: {
  report: ConsistencyReport;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);

  if (!report.available) {
    return (
      <div
        style={{
          ...cardSurface(dark),
          padding: "22px 24px",
          display: "flex",
          alignItems: "center",
          gap: 14,
          animation: ENTRANCE,
          animationDelay: `${delay}ms`,
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
          <LIcon name="Repeat2" size={16} color={BURG} />
        </div>
        <div>
          <div
            style={{
              color: t.text,
              fontSize: 13.5,
              fontWeight: 700,
              marginBottom: 3,
            }}
          >
            Consistency analysis
          </div>
          <div style={{ color: t.textSub, fontSize: 12.5 }}>
            {report.message ??
              "Run 2+ iterations of this experiment to see consistency analysis."}
          </div>
        </div>
      </div>
    );
  }

  const score = report.avgCosineSimilarity;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        animation: ENTRANCE,
        animationDelay: `${delay}ms`,
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 2,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            background: BURG_DIM,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <LIcon name="Repeat2" size={14} color={BURG} />
        </div>
        <span
          style={{
            color: t.text,
            fontWeight: 800,
            fontSize: 13.5,
            letterSpacing: 0.3,
          }}
        >
          Consistency analysis
        </span>
        <span
          style={{
            ...labelStyle(dark),
            marginLeft: 6,
            color: t.textDim,
          }}
        >
          {report.trialsWithAnswers} / {report.trialCount} runs analysed
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(320px, 100%), 1fr))",
          gap: 14,
        }}
      >
        {/* Cosine similarity score card */}
        <StatCard
          title="Semantic similarity"
          icon="Gauge"
          dark={dark}
          minHeight={160}
        >
          {score !== null ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                height: "100%",
                padding: "8px 0",
              }}
            >
              <span
                style={{
                  fontSize: 52,
                  fontWeight: 800,
                  letterSpacing: -2,
                  color: similarityColor(score),
                  fontVariantNumeric: "tabular-nums",
                  lineHeight: 1,
                }}
              >
                {(score * 100).toFixed(1)}%
              </span>
              <span
                style={{
                  color: similarityColor(score),
                  fontSize: 12,
                  fontWeight: 700,
                  fontFamily: MONO,
                  letterSpacing: 1,
                  textTransform: "uppercase",
                }}
              >
                {similarityLabel(score)} consistency
              </span>
              <span
                style={{ color: t.textDim, fontSize: 11, fontFamily: MONO }}
              >
                avg cosine similarity · {report.pairwiseScores.length} pair
                {report.pairwiseScores.length === 1 ? "" : "s"}
              </span>
            </div>
          ) : (
            <div
              style={{
                color: t.textSub,
                fontSize: 12.5,
                lineHeight: 1.6,
                padding: 8,
              }}
            >
              Embedding API unavailable — similarity score could not be
              computed.
            </div>
          )}
        </StatCard>

        {/* AI summary card */}
        <StatCard
          title="AI consistency summary"
          icon="Sparkles"
          dark={dark}
          minHeight={160}
        >
          {report.aiSummary ? (
            <div
              style={{
                color: t.text,
                fontSize: 13,
                lineHeight: 1.65,
                overflowY: "auto",
                maxHeight: 220,
                paddingRight: 4,
              }}
            >
              {report.aiSummary}
            </div>
          ) : (
            <div style={{ color: t.textSub, fontSize: 12.5, lineHeight: 1.6 }}>
              AI summary unavailable — no LLM provider is configured.
            </div>
          )}
        </StatCard>
      </div>

      {/* Pairwise scores table (only when > 1 pair) */}
      {report.pairwiseScores.length > 1 && (
        <StatCard title="Pairwise scores" icon="TableCellsMerge" dark={dark}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 6,
              maxHeight: 200,
              overflowY: "auto",
            }}
          >
            {report.pairwiseScores.map((p, i) => {
              const sim = p.cosineSimilarity;
              const pct = (sim * 100).toFixed(1);
              const color = similarityColor(sim);
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    fontSize: 11.5,
                  }}
                >
                  <span
                    style={{
                      color: t.textDim,
                      fontFamily: MONO,
                      fontSize: 10,
                      minWidth: 240,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {p.trialIdA.slice(0, 8)}… ↔ {p.trialIdB.slice(0, 8)}…
                  </span>
                  <div
                    style={{
                      flex: 1,
                      height: 4,
                      borderRadius: 2,
                      background: t.inputBg,
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${sim * 100}%`,
                        height: "100%",
                        borderRadius: 2,
                        background: color,
                      }}
                    />
                  </div>
                  <span
                    style={{
                      color,
                      fontFamily: MONO,
                      fontWeight: 700,
                      fontSize: 11,
                      minWidth: 44,
                      textAlign: "right",
                    }}
                  >
                    {pct}%
                  </span>
                </div>
              );
            })}
          </div>
        </StatCard>
      )}
    </div>
  );
}
