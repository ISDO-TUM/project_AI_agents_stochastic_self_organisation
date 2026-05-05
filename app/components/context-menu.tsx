"use client";

import { useEffect, useRef } from "react";
import { LIcon } from "@/lib/icons";
import { BURG_LT, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

export interface ContextMenuItem {
  label: string;
  icon: string;
  fn: () => void;
  danger?: boolean;
}

interface ContextMenuProps {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      style={{
        position: "fixed",
        left: x,
        top: y,
        zIndex: 9999,
        background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,253,255,0.98)",
        backdropFilter: "blur(24px)",
        border: `1px solid ${t.borderHi}`,
        borderRadius: 12,
        boxShadow: dark
          ? "0 0 0 1px rgba(139,26,47,0.14), 0 8px 40px rgba(0,0,0,0.6)"
          : "0 0 0 1px rgba(139,26,47,0.10), 0 8px 40px rgba(0,0,0,0.12)",
        overflow: "hidden",
        minWidth: 164,
        animation: "fadeIn 0.1s ease-out",
      }}
    >
      {items.map((item) => (
        <button
          key={item.label}
          onClick={() => {
            item.fn();
            onClose();
          }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            width: "100%",
            padding: "11px 16px",
            textAlign: "left",
            background: "none",
            border: "none",
            color: item.danger ? BURG_LT : t.text,
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = t.hover)
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = "none")
          }
        >
          <LIcon
            name={item.icon}
            size={14}
            color={item.danger ? BURG_LT : t.textSub}
          />
          {item.label}
        </button>
      ))}
    </div>
  );
}
