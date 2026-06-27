"use client";

import * as HoverCardPrimitive from "@radix-ui/react-hover-card";
import { forwardRef } from "react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

export const HoverCard = HoverCardPrimitive.Root;
export const HoverCardTrigger = HoverCardPrimitive.Trigger;

export const HoverCardContent = forwardRef<
  React.ElementRef<typeof HoverCardPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof HoverCardPrimitive.Content>
>(({ children, sideOffset = 8, ...props }, ref) => {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <HoverCardPrimitive.Portal>
      <HoverCardPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        style={{
          background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,253,255,0.98)",
          backdropFilter: "blur(20px)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 10,
          boxShadow: dark
            ? "0 8px 32px rgba(0,0,0,0.55)"
            : "0 8px 28px rgba(0,0,0,0.14)",
          padding: "10px 12px",
          minWidth: 160,
          maxWidth: 240,
          fontSize: 11.5,
          color: t.text,
          zIndex: 9999,
          animation: "selectIn 0.15s cubic-bezier(0.16,1,0.3,1)",
        }}
        {...props}
      >
        {children}
      </HoverCardPrimitive.Content>
    </HoverCardPrimitive.Portal>
  );
});
HoverCardContent.displayName = "HoverCardContent";
