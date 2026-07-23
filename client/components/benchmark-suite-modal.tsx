"use client";

import { useMemo, useState } from "react";
import {
  BenchmarkConsensusMode,
  BenchmarkMechanismConfig,
  TopologyMode,
} from "@/lib/types";
import { createBenchmarkSuite } from "@/lib/api";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

const MODES: { mode: BenchmarkConsensusMode; label: string; hint: string }[] = [
  {
    mode: "broadcast_no_consensus",
    label: "Broadcast",
    hint: "Baseline with no reducer.",
  },
  {
    mode: "weighted_opinion_pooling",
    label: "Weighted pooling",
    hint: "Trust-weighted convergence.",
  },
  {
    mode: "plurality_voting",
    label: "Plurality vote",
    hint: "Vote tally with winner.",
  },
  {
    mode: "bidding",
    label: "Bidding",
    hint: "Agents bid for the final answer.",
  },
];

const TOPOLOGIES: { topology: TopologyMode; label: string }[] = [
  { topology: "static", label: "Static" },
  { topology: "dynamic", label: "Dynamic" },
];
const BIDDING_TOPOLOGY: TopologyMode = "dynamic";

interface BenchmarkSuiteModalProps {
  datasetId: string | null;
  prompt: string;
  fanout: number;
  agentCount: number;
  onCancel: () => void;
  onStarted: (suiteId: string) => void;
}

function keyFor(topology: TopologyMode, mode: BenchmarkConsensusMode) {
  return `${topology}:${mode}`;
}

export function BenchmarkSuiteModal({
  datasetId,
  prompt,
  fanout,
  agentCount,
  onCancel,
  onStarted,
}: BenchmarkSuiteModalProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [mechanisms, setMechanisms] = useState<BenchmarkMechanismConfig[]>(
    () => [
      ...TOPOLOGIES.flatMap(({ topology }) =>
        MODES.filter(({ mode }) => mode !== "bidding").map(({ mode }) => ({
          topology,
          mode,
          runs: 5,
        })),
      ),
      { topology: BIDDING_TOPOLOGY, mode: "bidding", runs: 5 },
    ],
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedPairs = useMemo(
    () => new Set(mechanisms.map((item) => keyFor(item.topology, item.mode))),
    [mechanisms],
  );
  const plannedTrials = mechanisms.reduce((sum, item) => sum + item.runs, 0);
  const trimmedPrompt = prompt.trim();
  const canStart =
    !submitting &&
    !!datasetId &&
    trimmedPrompt.length > 0 &&
    mechanisms.length > 0 &&
    agentCount >= 2;

  const togglePair = (topology: TopologyMode, mode: BenchmarkConsensusMode) => {
    const key = keyFor(topology, mode);
    setMechanisms((current) => {
      if (current.some((item) => keyFor(item.topology, item.mode) === key)) {
        return current.filter(
          (item) => keyFor(item.topology, item.mode) !== key,
        );
      }
      return [...current, { topology, mode, runs: 5 }];
    });
  };

  const runsFor = (topology: TopologyMode, mode: BenchmarkConsensusMode) =>
    mechanisms.find((item) => item.topology === topology && item.mode === mode)
      ?.runs ?? 5;

  const setRuns = (
    topology: TopologyMode,
    mode: BenchmarkConsensusMode,
    runs: number,
  ) => {
    setMechanisms((current) =>
      current.map((item) =>
        item.topology === topology && item.mode === mode
          ? { ...item, runs: Math.max(1, Math.min(20, runs || 1)) }
          : item,
      ),
    );
  };

  const handleStart = async () => {
    if (!canStart || !datasetId) return;
    setSubmitting(true);
    setError(null);
    try {
      const started = await createBenchmarkSuite({
        prompt: trimmedPrompt,
        datasetId,
        topology: "static",
        fanout,
        rounds: 3,
        mechanisms,
      });
      onStarted(started.suiteId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 5000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 18,
        background: dark ? "rgba(3,2,8,0.62)" : "rgba(255,255,255,0.58)",
        backdropFilter: "blur(12px)",
      }}
    >
      <div
        style={{
          width: "min(760px, 100%)",
          maxHeight: "min(760px, calc(100vh - 36px))",
          overflowY: "auto",
          background: dark ? "rgba(10,8,18,0.98)" : "rgba(255,253,255,0.98)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 14,
          boxShadow: dark
            ? "0 24px 70px rgba(0,0,0,0.72)"
            : "0 24px 60px rgba(45,30,50,0.16)",
          color: t.text,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 18px",
            borderBottom: `1px solid ${t.border}`,
          }}
        >
          <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
            <LIcon name="FlaskConical" size={16} color={BURG_LT} />
            <div>
              <div style={{ fontSize: 14, fontWeight: 800 }}>
                Benchmark Suite
              </div>
              <div style={{ fontSize: 11.5, color: t.textSub }}>
                {datasetId ?? "No benchmark imported"} · {agentCount} agents
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            style={{
              background: "transparent",
              border: "none",
              color: t.textSub,
              cursor: "pointer",
              padding: 6,
            }}
          >
            <LIcon name="X" size={16} color="currentColor" />
          </button>
        </div>

        <div style={{ padding: 18, display: "grid", gap: 16 }}>
          <div
            style={{
              background: t.inputBg,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              padding: 12,
              display: "grid",
              gap: 7,
            }}
          >
            <div style={{ color: t.textSub, fontSize: 11, fontWeight: 800 }}>
              Prompt
            </div>
            <div style={{ color: t.text, fontSize: 12.5, lineHeight: 1.45 }}>
              {trimmedPrompt || "Import a benchmark dataset first."}
            </div>
          </div>

          <div>
            <div
              style={{
                fontSize: 11,
                fontWeight: 800,
                color: t.textSub,
                marginBottom: 8,
              }}
            >
              Consensus options
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {MODES.map(({ mode, label, hint }) => (
                <div
                  key={mode}
                  style={{
                    border: `1px solid ${t.border}`,
                    borderRadius: 8,
                    padding: 12,
                    display: "grid",
                    gap: 11,
                    background: t.inputBg,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      justifyContent: "space-between",
                      gap: 12,
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{ color: t.text, fontSize: 13, fontWeight: 900 }}
                      >
                        {label}
                      </div>
                      <div
                        style={{
                          color: t.textDim,
                          fontSize: 11.5,
                          marginTop: 3,
                        }}
                      >
                        {hint}
                      </div>
                    </div>
                    <div
                      style={{
                        color: t.textSub,
                        fontSize: 11,
                        fontWeight: 800,
                        whiteSpace: "nowrap",
                      }}
                    >
                      Runs
                    </div>
                  </div>
                  {mode === "bidding" ? (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "minmax(0, 1fr) 72px",
                        gap: 8,
                        alignItems: "center",
                      }}
                    >
                      {(() => {
                        const checked = selectedPairs.has(
                          keyFor(BIDDING_TOPOLOGY, mode),
                        );
                        return (
                          <>
                            <button
                              type="button"
                              disabled={submitting}
                              onClick={() => togglePair(BIDDING_TOPOLOGY, mode)}
                              style={{
                                background: checked
                                  ? dark
                                    ? "rgba(139,26,47,0.32)"
                                    : "rgba(139,26,47,0.12)"
                                  : dark
                                    ? "rgba(255,255,255,0.04)"
                                    : "#fff",
                                border: `1px solid ${
                                  checked ? BURG : t.border
                                }`,
                                borderRadius: 8,
                                color: checked ? t.text : t.textSub,
                                cursor: submitting ? "not-allowed" : "pointer",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                gap: 7,
                                fontSize: 12,
                                fontWeight: 900,
                                minHeight: 36,
                                padding: "8px 10px",
                              }}
                            >
                              <LIcon
                                name={checked ? "Check" : "Circle"}
                                size={13}
                                color="currentColor"
                              />
                              Bidding
                            </button>
                            <input
                              type="number"
                              min={1}
                              max={20}
                              value={runsFor(BIDDING_TOPOLOGY, mode)}
                              disabled={!checked || submitting}
                              onChange={(e) =>
                                setRuns(
                                  BIDDING_TOPOLOGY,
                                  mode,
                                  Number(e.target.value),
                                )
                              }
                              style={{
                                width: "100%",
                                background: dark
                                  ? "rgba(255,255,255,0.04)"
                                  : "#fff",
                                border: `1px solid ${
                                  checked ? BURG : t.border
                                }`,
                                borderRadius: 8,
                                color: t.text,
                                padding: "8px 9px",
                                fontSize: 13,
                                fontWeight: 800,
                                textAlign: "center",
                              }}
                            />
                          </>
                        );
                      })()}
                    </div>
                  ) : (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                        gap: 8,
                      }}
                    >
                      {TOPOLOGIES.map(({ topology, label: topologyLabel }) => {
                        const checked = selectedPairs.has(
                          keyFor(topology, mode),
                        );
                        return (
                          <div
                            key={`${mode}-${topology}`}
                            style={{
                              display: "grid",
                              gridTemplateColumns: "minmax(0, 1fr) 72px",
                              gap: 8,
                              alignItems: "center",
                            }}
                          >
                            <button
                              type="button"
                              disabled={submitting}
                              onClick={() => togglePair(topology, mode)}
                              style={{
                                background: checked
                                  ? dark
                                    ? "rgba(139,26,47,0.32)"
                                    : "rgba(139,26,47,0.12)"
                                  : dark
                                    ? "rgba(255,255,255,0.04)"
                                    : "#fff",
                                border: `1px solid ${
                                  checked ? BURG : t.border
                                }`,
                                borderRadius: 8,
                                color: checked ? t.text : t.textSub,
                                cursor: submitting ? "not-allowed" : "pointer",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                gap: 7,
                                fontSize: 12,
                                fontWeight: 900,
                                minHeight: 36,
                                padding: "8px 10px",
                              }}
                            >
                              <LIcon
                                name={checked ? "Check" : "Circle"}
                                size={13}
                                color="currentColor"
                              />
                              {topologyLabel}
                            </button>
                            <input
                              type="number"
                              min={1}
                              max={20}
                              value={runsFor(topology, mode)}
                              disabled={!checked || submitting}
                              onChange={(e) =>
                                setRuns(topology, mode, Number(e.target.value))
                              }
                              style={{
                                width: "100%",
                                background: dark
                                  ? "rgba(255,255,255,0.04)"
                                  : "#fff",
                                border: `1px solid ${
                                  checked ? BURG : t.border
                                }`,
                                borderRadius: 8,
                                color: t.text,
                                padding: "8px 9px",
                                fontSize: 13,
                                fontWeight: 800,
                                textAlign: "center",
                              }}
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div style={{ color: t.textSub, fontSize: 12, fontWeight: 700 }}>
            Planned trials: {plannedTrials}
          </div>

          {!datasetId && (
            <div style={{ color: BURG, fontSize: 12, fontWeight: 700 }}>
              Import a benchmark dataset from the Import menu first.
            </div>
          )}
          {agentCount < 2 && (
            <div style={{ color: BURG, fontSize: 12, fontWeight: 700 }}>
              Benchmarks need at least 2 agents.
            </div>
          )}
          {error && (
            <div style={{ color: BURG, fontSize: 12, lineHeight: 1.45 }}>
              {error}
            </div>
          )}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            padding: "14px 18px 18px",
            borderTop: `1px solid ${t.border}`,
          }}
        >
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            style={{
              background: "transparent",
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              color: t.textSub,
              cursor: submitting ? "not-allowed" : "pointer",
              fontSize: 12,
              fontWeight: 800,
              padding: "9px 13px",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleStart}
            disabled={!canStart}
            style={{
              background: canStart ? BURG : t.inputBg,
              border: "none",
              borderRadius: 8,
              color: canStart ? "#fff" : t.textDim,
              cursor: canStart ? "pointer" : "not-allowed",
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              fontWeight: 900,
              padding: "10px 15px",
            }}
          >
            <LIcon name="Play" size={14} color="currentColor" />
            {submitting ? "Starting..." : "Start benchmark"}
          </button>
        </div>
      </div>
    </div>
  );
}
