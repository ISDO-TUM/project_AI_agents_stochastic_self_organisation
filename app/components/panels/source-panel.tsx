"use client";

import { useState } from "react";
import { Source } from "@/lib/types";
import { uuid } from "@/lib/utils";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

import { FLabel, FInput, FBtn, PanelShell } from "./panel-primitives";

interface SourcePanelProps {
  source: Source | null;
  onSave: (source: Source) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

export function SourcePanel({
  source,
  onSave,
  onDelete,
  onClose,
}: SourcePanelProps) {
  const [name, setName] = useState(source?.name ?? "");
  const [content, setContent] = useState(source?.content ?? "");

  const handleSave = () => {
    const position = source?.position ?? {
      x: 300 + Math.random() * 380,
      y: 260 + Math.random() * 200,
    };
    onSave({ id: source?.id ?? uuid(), name, type: "text", content, position });
  };

  const { dark } = useTheme();
  const t = getTheme(dark);

  return (
    <PanelShell
      title={source ? "Configure File" : "New File"}
      onClose={onClose}
      icon={source ? "FileText" : "Plus"}
    >
      <FLabel>Name</FLabel>
      <FInput value={name} onChange={setName} placeholder="filename.txt" />
      <FLabel>Content</FLabel>
      <FInput
        value={content}
        onChange={setContent}
        placeholder="Paste or type file content…"
        multiline
        rows={8}
      />
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
          {source ? "Save File" : "Create File"}
        </FBtn>
      </div>
    </PanelShell>
  );
}
