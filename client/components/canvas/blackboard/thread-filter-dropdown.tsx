"use client";

import { useState } from "react";
import { ChevronDown, ListFilter } from "lucide-react";
import { ThreadInfo } from "@/lib/types";
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
  pos: { x: number; y: number };
}

export function ThreadFilterDropdown({
  threads,
  activeThreadId,
  onSelect,
  pos,
}: ThreadFilterDropdownProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [open, setOpen] = useState(false);
  const activeTitle =
    threads.find((th) => th.id === activeThreadId)?.title ?? "All threads";

  return (
    <div
      style={{
        position: "absolute",
        left: pos.x,
        top: pos.y,
        zIndex: 19,
      }}
    >
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "5px 12px",
              borderRadius: 100,
              border: `1.5px solid ${t.border}`,
              background: t.pill,
              color: t.textSub,
              fontSize: 10.5,
              fontWeight: 700,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              cursor: "pointer",
              whiteSpace: "nowrap",
              backdropFilter: "blur(10px)",
            }}
          >
            <ListFilter size={11} strokeWidth={2} />
            {activeTitle}
            <ChevronDown
              size={10}
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
            {threads.map((th) => (
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
                  background:
                    activeThreadId === th.id
                      ? dark
                        ? "rgba(139,26,47,0.18)"
                        : "rgba(139,26,47,0.08)"
                      : "none",
                  color: activeThreadId === th.id ? BURG : t.text,
                  fontSize: 12,
                  fontWeight: activeThreadId === th.id ? 700 : 500,
                  cursor: "pointer",
                }}
              >
                {th.title}
              </button>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
