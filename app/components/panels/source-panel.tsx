"use client";

import { useState } from "react";
import { Source, SourceType } from "@/lib/types";
import { uuid } from "@/lib/utils";
import { BURG_DIM, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

import { LIcon } from "@/lib/icons";
import { FLabel, FInput, FSelect, FBtn, PanelShell } from "./panel-primitives";

interface SourcePanelProps {
  source: Source | null;
  onSave: (source: Source) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

interface SourceForm {
  name: string;
  type: SourceType;
  content: string;
}

export function SourcePanel({
  source,
  onSave,
  onDelete,
  onClose,
}: SourcePanelProps) {
  const [form, setForm] = useState<SourceForm>({
    name: source?.name ?? "",
    type: source?.type ?? "text",
    content: source?.content ?? "",
  });

  const set = <K extends keyof SourceForm>(k: K, v: SourceForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const handleSave = () => {
    const position = source?.position ?? {
      x: 300 + Math.random() * 380,
      y: 260 + Math.random() * 200,
    };
    onSave({ ...form, id: source?.id ?? uuid(), position });
  };

  const { dark } = useTheme();
  const t = getTheme(dark);

  return (
    <PanelShell
      title={source ? "Configure Source" : "New Source"}
      onClose={onClose}
      icon={source ? "FileText" : "Plus"}
    >
      <FLabel>Name</FLabel>
      <FInput
        value={form.name}
        onChange={(v) => set("name", v)}
        placeholder="Source name"
      />
      <FLabel>Type</FLabel>
      <FSelect
        value={form.type}
        onChange={(v) => set("type", v as SourceType)}
        options={[
          { value: "text", label: "Text" },
          { value: "document", label: "Document" },
        ]}
      />
      <FLabel>Content</FLabel>
      {form.type === "document" ? (
        <div
          style={{
            border: `1.5px dashed ${BURG_DIM}`,
            borderRadius: 10,
            padding: 28,
            textAlign: "center",
            color: t.textDim,
            fontSize: 13,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
          }}
        >
          <LIcon name="Upload" size={24} color={t.textDim} />
          <span>File upload placeholder</span>
        </div>
      ) : (
        <FInput
          value={form.content}
          onChange={(v) => set("content", v)}
          placeholder="Paste or type source content…"
          multiline
          rows={8}
        />
      )}
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
          {source ? "Save Source" : "Create Source"}
        </FBtn>
      </div>
    </PanelShell>
  );
}
