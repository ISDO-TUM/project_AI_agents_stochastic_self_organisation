"use client";

import { useCallback, useState } from "react";
import { Heart, ShieldCheck, ChevronDown } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT } from "@/lib/theme";
import { fetchAgentTrust } from "@/lib/api";
import { AgentSwarmRole, AgentTrustEntry } from "@/lib/types";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface AgentTrustPanelProps {
  agentId: string;
  agentName: string;
  role: AgentSwarmRole | null;
  citationCount: number;
  concedingTemperature?: number;
  trigger: React.ReactNode;
}

export function AgentTrustPanel({
  agentId,
  agentName,
  role,
  citationCount,
  concedingTemperature,
  trigger,
}: AgentTrustPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [trustVector, setTrustVector] = useState<AgentTrustEntry[] | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const loadTrust = useCallback(() => {
    if (trustVector !== null || loading) return;
    setLoading(true);
    fetchAgentTrust(agentId)
      .then(setTrustVector)
      .catch(() => setTrustVector([]))
      .finally(() => setLoading(false));
  }, [agentId, trustVector, loading]);

  return (
    <Popover onOpenChange={(open) => open && loadTrust()}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 8,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
            {agentName}
          </span>
          {role && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 800,
                color: BURG_LT,
                background: "rgba(139,26,47,0.13)",
                borderRadius: 4,
                padding: "1.5px 6px",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              {role}
            </span>
          )}
          <span
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11.5,
              fontWeight: 700,
              color: t.textSub,
            }}
          >
            <Heart size={11} strokeWidth={2} color="#c0392b" />
            {citationCount} this run
          </span>
        </div>

        {concedingTemperature !== undefined && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, color: t.textDim, marginBottom: 3 }}>
              Conceding temperature: {concedingTemperature.toFixed(2)}
            </div>
            <div
              style={{
                height: 5,
                borderRadius: 100,
                background: dark
                  ? "rgba(255,255,255,0.08)"
                  : "rgba(0,0,0,0.08)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${concedingTemperature * 100}%`,
                  background: BURG_LT,
                  borderRadius: 100,
                }}
              />
            </div>
          </div>
        )}

        <button
          onClick={() => setExpanded((e) => !e)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
            fontSize: 10.5,
            fontWeight: 700,
            color: t.textDim,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          <ShieldCheck size={11} strokeWidth={2} />
          Trust Vector (cross-run)
          <ChevronDown
            size={10}
            style={{
              transform: expanded ? "rotate(180deg)" : "none",
              transition: "transform 0.15s",
            }}
          />
        </button>

        {expanded && (
          <div style={{ marginTop: 8 }}>
            {loading && (
              <div style={{ fontSize: 11, color: t.textDim }}>Loading…</div>
            )}
            {!loading && trustVector?.length === 0 && (
              <div style={{ fontSize: 11, color: t.textDim }}>
                No cross-run history yet.
              </div>
            )}
            {!loading &&
              trustVector?.map((entry) => (
                <div key={entry.domain} style={{ marginBottom: 6 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 10.5,
                      color: t.textSub,
                      marginBottom: 2,
                    }}
                  >
                    <span>{entry.domain}</span>
                    <span>
                      {entry.trust_score.toFixed(2)} · {entry.runs_participated}{" "}
                      run
                      {entry.runs_participated === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 4,
                      borderRadius: 100,
                      background: dark
                        ? "rgba(255,255,255,0.07)"
                        : "rgba(0,0,0,0.07)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width: `${entry.trust_score * 100}%`,
                        background: "#3dba8c",
                        borderRadius: 100,
                      }}
                    />
                  </div>
                </div>
              ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
