"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { forwardRef, useState } from "react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG, BURG_DIM } from "@/lib/theme";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ children, disabled, ...props }, ref) => {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [hov, setHov] = useState(false);

  return (
    <SelectPrimitive.Trigger
      ref={ref}
      disabled={disabled}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        borderRadius: 100,
        border: `1px solid ${
          hov && !disabled ? "rgba(139,26,47,0.42)" : t.pillBorder
        }`,
        background: t.inputBg,
        color: disabled ? t.textDim : t.text,
        fontSize: 12,
        fontWeight: 600,
        padding: "5px 9px 5px 11px",
        marginRight: 6,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        outline: "none",
        transition: "border-color 0.18s, box-shadow 0.18s",
        boxShadow: hov && !disabled ? `0 0 0 3px ${BURG_DIM}` : "none",
        flexShrink: 0,
        whiteSpace: "nowrap",
        userSelect: "none",
      }}
      {...props}
    >
      {children}
      <ChevronDown
        size={10}
        className="select-chevron"
        style={{ color: t.textDim, flexShrink: 0 }}
      />
    </SelectPrimitive.Trigger>
  );
});
SelectTrigger.displayName = "SelectTrigger";

export const SelectContent = forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ children, position = "popper", ...props }, ref) => {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        ref={ref}
        position={position}
        sideOffset={8}
        style={
          {
            background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,253,255,0.98)",
            backdropFilter: "blur(24px)",
            WebkitBackdropFilter: "blur(24px)",
            border: `1px solid ${t.borderHi}`,
            borderRadius: 12,
            boxShadow: dark
              ? "0 0 0 1px rgba(139,26,47,0.14), 0 8px 40px rgba(0,0,0,0.6)"
              : "0 0 0 1px rgba(139,26,47,0.10), 0 8px 32px rgba(0,0,0,0.12)",
            overflow: "hidden",
            minWidth: 164,
            zIndex: 9999,
            animation: "selectIn 0.15s cubic-bezier(0.16,1,0.3,1)",
            padding: 4,
            "--select-hover": t.hover,
            "--select-checked": dark
              ? "rgba(139,26,47,0.15)"
              : "rgba(139,26,47,0.09)",
          } as React.CSSProperties
        }
        {...props}
      >
        <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
});
SelectContent.displayName = "SelectContent";

export const SelectItem = forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ children, ...props }, ref) => {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <SelectPrimitive.Item
      ref={ref}
      className="select-item"
      style={{
        display: "flex",
        alignItems: "center",
        padding: "9px 32px 9px 12px",
        borderRadius: 8,
        fontSize: 12,
        fontWeight: 600,
        color: t.text,
        cursor: "pointer",
        outline: "none",
        userSelect: "none",
        position: "relative",
        transition: "background 0.1s",
      }}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <span
        style={{
          position: "absolute",
          right: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 14,
          height: 14,
        }}
      >
        <SelectPrimitive.ItemIndicator>
          <Check size={11} style={{ color: BURG }} />
        </SelectPrimitive.ItemIndicator>
      </span>
    </SelectPrimitive.Item>
  );
});
SelectItem.displayName = "SelectItem";
