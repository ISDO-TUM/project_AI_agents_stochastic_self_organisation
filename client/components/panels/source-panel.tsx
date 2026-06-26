"use client";

import { useRef, useState } from "react";
import { Agent, Source, SourceType } from "@/lib/types";
import { uuid } from "@/lib/utils";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

import { FLabel, FInput, FSelect, FBtn, PanelShell } from "./panel-primitives";
import { BURG_LT } from "@/lib/theme";

interface SourcePanelProps {
  source: Source | null;
  /** Pre-selected type when creating a new source (source === null). */
  initialType?: SourceType;
  /** Available agents for assignment. */
  agents?: Agent[];
  onSave: (source: Source) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

const PREVIEW_MAX_HEIGHT = 420;

/** Minimal CSV preview — naive split is fine for an at-a-glance grid. Shows
 *  every row and column; the surrounding box scrolls both ways so a wide or
 *  tall table stays fully reachable (pair with widening the sidebar). */
function CsvPreview({ text, dark }: { text: string; dark: boolean }) {
  const t = getTheme(dark);
  const lines = text.trim().split(/\r?\n/);
  if (!text.trim()) return null;

  const rows = lines.map((r) => r.split(","));
  const [header, ...body] = rows;

  const cell: React.CSSProperties = {
    padding: "4px 8px",
    borderBottom: `1px solid ${t.border}`,
    borderRight: `1px solid ${t.border}`,
    fontSize: 11,
    fontFamily: "'JetBrains Mono', monospace",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    maxWidth: 120,
  };

  return (
    <div
      style={{
        marginTop: 8,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        overflow: "auto",
        maxHeight: PREVIEW_MAX_HEIGHT,
      }}
    >
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            {header.map((h, i) => (
              <th
                key={i}
                style={{
                  ...cell,
                  textAlign: "left",
                  fontWeight: 700,
                  color: t.text,
                  background: t.inputBg,
                  position: "sticky",
                  top: 0,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri}>
              {r.map((c, ci) => (
                <td key={ci} style={{ ...cell, color: t.textSub }}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SourcePanel({
  source,
  initialType,
  agents = [],
  onSave,
  onDelete,
  onClose,
}: SourcePanelProps) {
  const [name, setName] = useState(source?.name ?? "");
  const [content, setContent] = useState(source?.content ?? "");
  const [type, setType] = useState<SourceType>(
    source?.type ?? initialType ?? "text",
  );
  const [agentIds, setAgentIds] = useState<string[]>(
    source?.agentIds ?? [],
  );
  const fileInput = useRef<HTMLInputElement>(null);

  const isDataset = type === "dataset";

  const handleSave = () => {
    const position = source?.position ?? {
      x: 300 + Math.random() * 380,
      y: 260 + Math.random() * 200,
    };
    onSave({ id: source?.id ?? uuid(), name, type, content, position, agentIds });
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setContent(text);
    if (!name) setName(file.name);
    e.target.value = ""; // allow re-uploading the same file
  };

  const { dark } = useTheme();
  const t = getTheme(dark);

  const noun = isDataset ? "Dataset" : "File";

  return (
    <PanelShell
      title={source ? `Configure ${noun}` : `New ${noun}`}
      onClose={onClose}
      icon={isDataset ? "Table2" : source ? "FileText" : "Plus"}
    >
      <FLabel>Type</FLabel>
      <FSelect
        value={type}
        onChange={(v) => setType(v as SourceType)}
        options={[
          { value: "text", label: "Text file" },
          { value: "dataset", label: "Dataset (CSV)" },
        ]}
      />

      <FLabel>Name</FLabel>
      <FInput
        value={name}
        onChange={setName}
        placeholder={isDataset ? "data.csv" : "filename.txt"}
      />

      {agents.length > 0 && (
        <>
          <FLabel>Assign to agents</FLabel>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              marginBottom: 14,
            }}
          >
            {agents.map((agent) => {
              const selected = agentIds.includes(agent.id);
              return (
                <button
                  key={agent.id}
                  onClick={() =>
                    setAgentIds((prev) =>
                      selected
                        ? prev.filter((id) => id !== agent.id)
                        : [...prev, agent.id],
                    )
                  }
                  style={{
                    padding: "3px 10px",
                    borderRadius: 20,
                    border: selected
                      ? `1.5px solid ${BURG_LT}`
                      : `1.5px solid ${t.border}`,
                    background: selected
                      ? `${BURG_LT}22`
                      : t.inputBg,
                    color: selected ? BURG_LT : t.textSub,
                    fontSize: 12,
                    fontFamily: "'Space Grotesk', sans-serif",
                    fontWeight: selected ? 600 : 400,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                    whiteSpace: "nowrap",
                  }}
                >
                  {agent.name}
                </button>
              );
            })}
          </div>
        </>
      )}

      {isDataset && (
        <>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.tsv,text/csv"
            onChange={handleFile}
            style={{ display: "none" }}
          />
          <div style={{ marginBottom: 10 }}>
            <FBtn
              variant="ghost"
              onClick={() => fileInput.current?.click()}
              icon="Upload"
            >
              Upload CSV
            </FBtn>
          </div>
        </>
      )}

      <FLabel>{isDataset ? "CSV content" : "Content"}</FLabel>
      <FInput
        value={content}
        onChange={setContent}
        placeholder={
          isDataset
            ? "Upload a CSV above, or paste rows here…"
            : "Paste or type file content…"
        }
        multiline
        rows={isDataset ? 5 : 8}
      />

      {isDataset && <CsvPreview text={content} dark={dark} />}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 24,
          paddingTop: 16,
          borderTop: `1px solid ${t.border}`,
          gap: 10,
        }}
      >
        {source ? (
          <FBtn
            variant="danger"
            onClick={() => onDelete(source.id)}
            icon="Trash2"
          >
            Delete
          </FBtn>
        ) : (
          <div />
        )}
        <FBtn
          variant="primary"
          onClick={handleSave}
          icon={source ? undefined : "Plus"}
        >
          {source ? `Save ${noun}` : `Create ${noun}`}
        </FBtn>
      </div>
    </PanelShell>
  );
}
