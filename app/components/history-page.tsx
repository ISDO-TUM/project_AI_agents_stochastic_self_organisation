"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchAgents,
  fetchHistoryMessages,
  fetchHistoryTrials,
} from "@/lib/api";
import { Agent, HistoryMessage, HistoryTrial } from "@/lib/types";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon } from "@/lib/icons";

interface HistoryPageProps {
  onBack: () => void;
}

const ALL = "";

export function HistoryPage({ onBack }: HistoryPageProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [trials, setTrials] = useState<HistoryTrial[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [trialId, setTrialId] = useState(ALL);
  const [agentId, setAgentId] = useState(ALL);
  const [messageType, setMessageType] = useState(ALL);
  const [selected, setSelected] = useState<HistoryMessage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [trialRows, agentRows, messageRows] = await Promise.all([
        fetchHistoryTrials(),
        fetchAgents(),
        fetchHistoryMessages({
          trialId: trialId || undefined,
          agentId: agentId || undefined,
          messageType: messageType || undefined,
        }),
      ]);
      setTrials(trialRows);
      setAgents(agentRows);
      setMessages(messageRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [agentId, messageType, trialId]);

  useEffect(() => {
    void load();
  }, [load]);

  const messageTypes = useMemo(
    () => Array.from(new Set(messages.map((m) => m.messageType))).sort(),
    [messages],
  );

  const controlStyle: React.CSSProperties = {
    background: t.surface,
    color: t.text,
    border: `1px solid ${t.border}`,
    borderRadius: 8,
    padding: "8px 10px",
    fontSize: 12,
    minWidth: 170,
  };

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: t.bg,
        color: t.text,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          height: 58,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 22px",
          borderBottom: `1px solid ${t.border}`,
          background: t.surface,
        }}
      >
        <button
          onClick={onBack}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "transparent",
            border: "none",
            color: t.text,
            cursor: "pointer",
            fontSize: 13,
            fontWeight: 700,
          }}
        >
          <LIcon name="ArrowLeft" size={16} color="currentColor" />
          Canvas
        </button>
        <div style={{ fontSize: 14, fontWeight: 800 }}>Simulation History</div>
        <button
          onClick={() => void load()}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            background: t.hover,
            border: `1px solid ${t.border}`,
            borderRadius: 8,
            color: t.text,
            cursor: "pointer",
            fontSize: 12,
            fontWeight: 700,
            padding: "7px 10px",
          }}
        >
          <LIcon name="RefreshCw" size={14} color="currentColor" />
          Refresh
        </button>
      </div>

      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          padding: "14px 22px",
          borderBottom: `1px solid ${t.border}`,
          flexWrap: "wrap",
        }}
      >
        <select
          value={trialId}
          onChange={(e) => setTrialId(e.target.value)}
          style={controlStyle}
        >
          <option value={ALL}>All trials</option>
          {trials.map((trial) => (
            <option key={trial.id} value={trial.id}>
              {trial.description}
            </option>
          ))}
        </select>
        <select
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          style={controlStyle}
        >
          <option value={ALL}>All agents</option>
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
        <select
          value={messageType}
          onChange={(e) => setMessageType(e.target.value)}
          style={controlStyle}
        >
          <option value={ALL}>All message types</option>
          {messageTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <div style={{ color: t.textSub, fontSize: 12, marginLeft: "auto" }}>
          {loading
            ? "Loading..."
            : `${messages.length} message${messages.length === 1 ? "" : "s"}`}
        </div>
      </div>

      {error && (
        <div
          style={{
            color: "#fff",
            background: "rgba(139,26,47,0.9)",
            padding: "9px 22px",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ flex: 1, overflow: "auto" }} className="pscroll">
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}
        >
          <thead
            style={{ position: "sticky", top: 0, background: t.bg, zIndex: 1 }}
          >
            <tr>
              {["Round", "Phase", "From", "To", "Type", "Message"].map((h) => (
                <th
                  key={h}
                  style={{
                    textAlign: "left",
                    padding: "10px 14px",
                    borderBottom: `1px solid ${t.border}`,
                    color: t.textSub,
                    fontWeight: 800,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {messages.map((message) => (
              <tr
                key={message.id}
                onClick={() => setSelected(message)}
                style={{
                  cursor: "pointer",
                  borderBottom: `1px solid ${t.border}`,
                }}
              >
                <td style={{ padding: "10px 14px", width: 74 }}>
                  {message.roundIndex}
                </td>
                <td style={{ padding: "10px 14px", width: 130 }}>
                  {message.phase}
                </td>
                <td style={{ padding: "10px 14px", width: 180 }}>
                  {message.fromAgentName}
                </td>
                <td style={{ padding: "10px 14px", width: 180 }}>
                  {message.toAgentName}
                </td>
                <td style={{ padding: "10px 14px", width: 170 }}>
                  {message.messageType}
                </td>
                <td
                  style={{
                    padding: "10px 14px",
                    color: t.textSub,
                    maxWidth: 560,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {message.message || ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "rgba(0,0,0,0.28)",
            display: "flex",
            justifyContent: "flex-end",
            zIndex: 120,
          }}
          onClick={() => setSelected(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(560px, 92vw)",
              height: "100%",
              background: t.surface,
              borderLeft: `1px solid ${t.borderHi}`,
              padding: 22,
              overflow: "auto",
              boxShadow: "0 12px 36px rgba(0,0,0,0.24)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <div style={{ fontWeight: 800, fontSize: 15 }}>
                Message {selected.id}
              </div>
              <button
                onClick={() => setSelected(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: t.textSub,
                  cursor: "pointer",
                }}
              >
                <LIcon name="X" size={18} color="currentColor" />
              </button>
            </div>
            <div
              style={{
                marginTop: 16,
                color: t.textSub,
                lineHeight: 1.7,
                fontSize: 12,
              }}
            >
              <div>Trial: {selected.trialDescription}</div>
              <div>Round: {selected.roundIndex}</div>
              <div>
                Route: {selected.fromAgentName} {"->"} {selected.toAgentName}
              </div>
              <div>Type: {selected.messageType}</div>
            </div>
            <pre
              style={{
                marginTop: 18,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily: "inherit",
                fontSize: 13,
                lineHeight: 1.55,
                color: t.text,
              }}
            >
              {selected.message}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
