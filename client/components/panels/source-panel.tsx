"use client";

import { useRef, useState } from "react";
import { Source, SourceType } from "@/lib/types";
import { uuid } from "@/lib/utils";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

import { FLabel, FInput, FSelect, FBtn, PanelShell } from "./panel-primitives";

interface SourcePanelProps {
  source: Source | null;
  /** Pre-selected type when creating a new source (source === null). */
  initialType?: SourceType;
  onSave: (source: Source) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

const PREVIEW_ROWS = 6;
const PREVIEW_COLS = 6;

/** Minimal CSV preview — naive split is fine for an at-a-glance grid. */
function CsvPreview({ text, dark }: { text: string; dark: boolean }) {
  const t = getTheme(dark);
  const lines = text.trim().split(/\r?\n/);
  if (!text.trim()) return null;

  const rows = lines.slice(0, PREVIEW_ROWS + 1).map((r) => r.split(","));
  const totalCols = Math.max(...rows.map((r) => r.length));
  const cols = Math.min(PREVIEW_COLS, totalCols);
  const [header, ...body] = rows;
  const moreRows = lines.length - 1 - body.length;
  const moreCols = totalCols - cols;

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
        maxHeight: 220,
      }}
    >
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            {header.slice(0, cols).map((h, i) => (
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
            {moreCols > 0 && (
              <th style={{ ...cell, color: t.textSub, background: t.inputBg }}>
                +{moreCols}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri}>
              {r.slice(0, cols).map((c, ci) => (
                <td key={ci} style={{ ...cell, color: t.textSub }}>
                  {c}
                </td>
              ))}
              {moreCols > 0 && <td style={{ ...cell, color: t.textSub }}>…</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {moreRows > 0 && (
        <div
          style={{
            padding: "5px 8px",
            fontSize: 11,
            color: t.textSub,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          +{moreRows} more row{moreRows === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}

export function SourcePanel({
  source,
  initialType,
  onSave,
  onDelete,
  onClose,
}: SourcePanelProps) {
  const [name, setName] = useState(source?.name ?? "");
  const [content, setContent] = useState(source?.content ?? "");
  const [type, setType] = useState<SourceType>(
    source?.type ?? initialType ?? "text",
  );
  const fileInput = useRef<HTMLInputElement>(null);

  const isDataset = type === "dataset";

  const handleSave = () => {
    const position = source?.position ?? {
      x: 300 + Math.random() * 380,
      y: 260 + Math.random() * 200,
    };
    onSave({ id: source?.id ?? uuid(), name, type, content, position });
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
