"use client";

import { useState } from "react";
import { ChevronDown, ListFilter } from "lucide-react";
import { DraftEntry, ThreadInfo } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG } from "@/lib/theme";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface ThreadFilterDropdownProps {
  threads: ThreadInfo[];
  activeThreadId: string | null;
  onSelect: (id: string | null) => void;
  /** When supplied, a mini activity bar is rendered next to each thread row. */
  draftEntries?: DraftEntry[];
}

export function ThreadFilterDropdown({
  threads,
  activeThreadId,
  onSelect,
  draftEntries = [],
}: ThreadFilterDropdownProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [open, setOpen] = useState(false);
  const activeTitle =
    threads.find((th) => th.id === activeThreadId)?.title ?? "All threads";

  // Per-thread visible entry counts for the activity heatmap
  const countByThread = draftEntries.reduce<Record<string, number>>(
    (acc, e) => {
      if (e.is_visible) acc[e.thread_id] = (acc[e.thread_id] ?? 0) + 1;
      return acc;
    },
    {},
  );
  const maxCount = Math.max(1, ...Object.values(countByThread));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "3px 9px",
            borderRadius: 100,
            border: `1px solid rgba(139,26,47,0.35)`,
            background: "rgba(139,26,47,0.12)",
            color: "#C4374F",
            fontSize: 10,
            fontWeight: 700,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          <ListFilter size={10} strokeWidth={2} />
          {activeTitle}
          <ChevronDown
            size={9}
            style={{
              transform: open ? "rotate(180deg)" : "none",
              transition: "transform 0.15s",
            }}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent>
        {/* PopoverContent spreads incoming props after its own `style={{}}`
              (see client/components/ui/popover.tsx), so a `style` prop here
              would replace its background/border/shadow entirely rather than
              merge — use an inner wrapper for layout instead of overriding
              PopoverContent's own style. Its default padding(14)/minWidth(240)
              are left as-is. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <button
            onClick={() => {
              onSelect(null);
              setOpen(false);
            }}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "7px 10px",
              borderRadius: 8,
              border: "none",
              background:
                activeThreadId === null
                  ? dark
                    ? "rgba(139,26,47,0.18)"
                    : "rgba(139,26,47,0.08)"
                  : "none",
              color: activeThreadId === null ? BURG : t.text,
              fontSize: 12,
              fontWeight: activeThreadId === null ? 700 : 500,
              cursor: "pointer",
            }}
          >
            All threads
          </button>
          {threads.map((th) => {
            const count = countByThread[th.id] ?? 0;
            const pct = count / maxCount;
            const isActive = activeThreadId === th.id;
            return (
              <button
                key={th.id}
                onClick={() => {
                  onSelect(th.id);
                  setOpen(false);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "7px 10px",
                  borderRadius: 8,
                  border: "none",
                  background: isActive
                    ? dark
                      ? "rgba(139,26,47,0.18)"
                      : "rgba(139,26,47,0.08)"
                    : "none",
                  color: isActive ? BURG : t.text,
                  fontSize: 12,
                  fontWeight: isActive ? 700 : 500,
                  cursor: "pointer",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ flex: 1 }}>{th.title}</span>
                  {draftEntries.length > 0 && (
                    <span
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 5,
                        flexShrink: 0,
                      }}
                    >
                      <span style={{ fontSize: 10, color: t.textDim }}>
                        {count}
                      </span>
                      <span
                        style={{
                          width: 40,
                          height: 4,
                          borderRadius: 2,
                          background: dark
                            ? "rgba(255,255,255,0.08)"
                            : "rgba(0,0,0,0.08)",
                          overflow: "hidden",
                          display: "inline-block",
                        }}
                      >
                        <span
                          style={{
                            display: "block",
                            height: "100%",
                            width: `${Math.round(pct * 100)}%`,
                            background: isActive ? BURG : "#3dba8c",
                            borderRadius: 2,
                            transition: "width 0.4s ease",
                          }}
                        />
                      </span>
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
