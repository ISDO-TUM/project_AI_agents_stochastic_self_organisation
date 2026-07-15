"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBenchmarkSuiteResults, fetchBenchmarkSuites } from "@/lib/api";
import { LIcon } from "@/lib/icons";
import { BURG, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import type { BenchmarkSuiteResults, BenchmarkSuiteSummary } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  SkeletonCard,
  cardSurface,
} from "./primitives";

function formatPercent(value: number | null) {
  if (value == null) return "n/a";
  return `${Math.round(value * 100)}%`;
}

function formatNumber(value: number | null) {
  if (value == null) return "n/a";
  return value.toFixed(value >= 10 ? 0 : 1);
}

function formatInteger(value: number | null) {
  if (value == null) return "n/a";
  return new Intl.NumberFormat().format(Math.round(value));
}

function formatCost(value: number | null) {
  if (value == null) return "n/a";
  return value > 0 ? `$${value.toFixed(4)}` : "$0.0000";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function labelMode(mode: string) {
  return mode
    .replace("broadcast_no_consensus", "Broadcast")
    .replace("weighted_opinion_pooling", "Weighted pooling")
    .replace("plurality_voting", "Plurality vote")
    .replace("bidding", "Bidding");
}

function labelTopology(topology: string) {
  return topology.replace("static", "Static").replace("dynamic", "Dynamic");
}

export function BenchmarkSuiteResultsView() {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [suites, setSuites] = useState<BenchmarkSuiteSummary[]>([]);
  const [suiteId, setSuiteId] = useState<string | null>(null);
  const [results, setResults] = useState<BenchmarkSuiteResults | null>(null);
  const [loadingSuites, setLoadingSuites] = useState(true);
  const [loadingResults, setLoadingResults] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSuites = useCallback(() => {
    setLoadingSuites(true);
    return fetchBenchmarkSuites()
      .then((rows) => {
        setSuites(rows);
        const latest =
          window.localStorage.getItem("latestBenchmarkSuiteId") || undefined;
        const preferred = rows.find((row) => row.id === latest);
        if (preferred) window.localStorage.removeItem("latestBenchmarkSuiteId");
        setSuiteId((current) => {
          if (preferred) return preferred.id;
          if (current && rows.some((row) => row.id === current)) return current;
          return rows[0]?.id ?? null;
        });
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setLoadingSuites(false));
  }, []);

  const loadResults = useCallback((id: string) => {
    setLoadingResults(true);
    setError(null);
    return fetchBenchmarkSuiteResults(id)
      .then(setResults)
      .catch((err) => {
        setResults(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoadingResults(false));
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      loadSuites();
    });
  }, [loadSuites]);

  useEffect(() => {
    if (!suiteId) {
      queueMicrotask(() => setResults(null));
      return;
    }
    queueMicrotask(() => {
      loadResults(suiteId);
    });
  }, [suiteId, loadResults]);

  useEffect(() => {
    if (!suiteId || results?.suite.status !== "running") return;
    const timer = window.setInterval(() => {
      loadSuites();
      loadResults(suiteId);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [suiteId, results?.suite.status, loadSuites, loadResults]);

  if (loadingSuites) {
    return <SkeletonCard height={260} dark={dark} />;
  }

  if (error && suites.length === 0) {
    return <ErrorState message={error} dark={dark} />;
  }

  if (suites.length === 0) {
    return (
      <EmptyState
        icon="FlaskConical"
        title="No benchmark suites yet"
        sub="Start a benchmark from Topology mode to compare consensus mechanisms."
        dark={dark}
      />
    );
  }

  const suite = results?.suite;
  const progress =
    suite && suite.plannedTrials > 0
      ? suite.completedTrials / suite.plannedTrials
      : 0;
  const totalCost =
    results?.aggregates.reduce((sum, row) => sum + row.totalCost, 0) ?? 0;
  const totalTokens =
    results?.aggregates.reduce((sum, row) => sum + row.totalTokens, 0) ?? 0;
  const totalGenerations =
    results?.aggregates.reduce((sum, row) => sum + row.generationCount, 0) ?? 0;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div
        style={{
          display: "grid",
          gap: 10,
          ...cardSurface(dark),
          borderRadius: 10,
          padding: 14,
        }}
      >
        <label style={{ display: "grid", gap: 7 }}>
          <span style={{ color: t.textSub, fontSize: 11, fontWeight: 800 }}>
            Benchmark suite
          </span>
          <select
            value={suiteId ?? ""}
            onChange={(e) => setSuiteId(e.target.value || null)}
            style={{
              background: t.inputBg,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              color: t.text,
              fontSize: 12.5,
              fontWeight: 700,
              padding: "9px 12px",
            }}
          >
            {suites.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name} · {row.completedTrials}/{row.plannedTrials} ·{" "}
                {formatDate(row.createdAt)}
              </option>
            ))}
          </select>
        </label>
        {suite && (
          <>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                color: t.textSub,
                fontSize: 12,
                fontWeight: 700,
                flexWrap: "wrap",
              }}
            >
              <span>{suite.datasetId}</span>
              <span>
                {suite.status} · {suite.completedTrials}/{suite.plannedTrials}{" "}
                trials
              </span>
            </div>
            <div
              style={{
                height: 7,
                background: t.inputBg,
                borderRadius: 99,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${Math.round(progress * 100)}%`,
                  background: BURG,
                  transition: "width 0.25s",
                }}
              />
            </div>
            <div style={{ color: t.textDim, fontSize: 12, lineHeight: 1.45 }}>
              {suite.prompt}
            </div>
            {results && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                  gap: 8,
                }}
              >
                {[
                  ["LLM cost", formatCost(totalCost)],
                  ["Tokens", formatInteger(totalTokens)],
                  ["Generations", formatInteger(totalGenerations)],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    style={{
                      background: t.inputBg,
                      border: `1px solid ${t.border}`,
                      borderRadius: 8,
                      padding: "9px 10px",
                    }}
                  >
                    <div
                      style={{
                        color: t.textSub,
                        fontSize: 10.5,
                        fontWeight: 800,
                      }}
                    >
                      {label}
                    </div>
                    <div
                      style={{ color: t.text, fontSize: 15, fontWeight: 900 }}
                    >
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {loadingResults && !results ? (
        <SkeletonCard height={260} dark={dark} />
      ) : results ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
              gap: 10,
            }}
          >
            {results.aggregates.map((row) => (
              <div
                key={`${row.topology}-${row.consensusMode}`}
                style={{
                  ...cardSurface(dark),
                  borderRadius: 10,
                  padding: 14,
                  display: "grid",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    color: t.text,
                    fontSize: 13,
                    fontWeight: 900,
                  }}
                >
                  <LIcon name="GitCompare" size={14} color={BURG} />
                  {labelTopology(row.topology)} · {labelMode(row.consensusMode)}
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                    gap: 8,
                    color: t.textSub,
                    fontSize: 11.5,
                    fontWeight: 700,
                  }}
                >
                  <span>Accuracy</span>
                  <strong style={{ color: t.text, textAlign: "right" }}>
                    {formatPercent(row.accuracy)}
                  </strong>
                  <span>Avg rounds</span>
                  <strong style={{ color: t.text, textAlign: "right" }}>
                    {formatNumber(row.avgRounds)}
                  </strong>
                  <span>Avg messages</span>
                  <strong style={{ color: t.text, textAlign: "right" }}>
                    {formatNumber(row.avgMessages)}
                  </strong>
                  <span>Avg tokens</span>
                  <strong style={{ color: t.text, textAlign: "right" }}>
                    {formatInteger(row.avgTokens)}
                  </strong>
                  <span>Avg cost</span>
                  <strong style={{ color: t.text, textAlign: "right" }}>
                    {formatCost(row.avgCost)}
                  </strong>
                  <span>Complete</span>
                  <strong style={{ color: t.text, textAlign: "right" }}>
                    {row.completed}/{row.runs}
                  </strong>
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              ...cardSurface(dark),
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "12px 14px",
                borderBottom: `1px solid ${t.border}`,
                color: t.text,
                fontSize: 13,
                fontWeight: 900,
              }}
            >
              Average comparison
            </div>
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  minWidth: 980,
                  borderCollapse: "collapse",
                  fontSize: 12,
                }}
              >
                <thead>
                  <tr style={{ color: t.textSub, textAlign: "left" }}>
                    <th style={{ padding: "10px 14px" }}>Topology</th>
                    <th style={{ padding: "10px 14px" }}>Mechanism</th>
                    <th style={{ padding: "10px 14px" }}>Runs</th>
                    <th style={{ padding: "10px 14px" }}>Accuracy</th>
                    <th style={{ padding: "10px 14px" }}>Avg rounds</th>
                    <th style={{ padding: "10px 14px" }}>Avg messages</th>
                    <th style={{ padding: "10px 14px" }}>Avg tokens</th>
                    <th style={{ padding: "10px 14px" }}>Avg cost</th>
                    <th style={{ padding: "10px 14px" }}>Total cost</th>
                  </tr>
                </thead>
                <tbody>
                  {results.aggregates.map((row) => (
                    <tr
                      key={`${row.topology}-${row.consensusMode}`}
                      style={{
                        borderTop: `1px solid ${t.border}`,
                        color: t.text,
                      }}
                    >
                      <td style={{ padding: "10px 14px", fontWeight: 800 }}>
                        {labelTopology(row.topology)}
                      </td>
                      <td style={{ padding: "10px 14px", fontWeight: 800 }}>
                        {labelMode(row.consensusMode)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {row.completed}/{row.runs}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {formatPercent(row.accuracy)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {formatNumber(row.avgRounds)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {formatNumber(row.avgMessages)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {formatInteger(row.avgTokens)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {formatCost(row.avgCost)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {formatCost(row.totalCost)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
