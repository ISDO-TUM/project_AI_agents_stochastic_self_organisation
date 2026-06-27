"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { forwardRef } from "react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverAnchor = PopoverPrimitive.Anchor;

export const PopoverContent = forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ children, sideOffset = 10, ...props }, ref) => {
  const { dark } = useTheme();
  const t = getTheme(dark);
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        style={{
          background: dark ? "rgba(8,6,16,0.98)" : "rgba(255,253,255,0.99)",
          backdropFilter: "blur(24px)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 14,
          boxShadow: dark
            ? "0 0 0 1px rgba(139,26,47,0.14), 0 16px 50px rgba(0,0,0,0.6)"
            : "0 0 0 1px rgba(139,26,47,0.10), 0 16px 40px rgba(0,0,0,0.16)",
          padding: 14,
          minWidth: 240,
          zIndex: 9999,
          animation: "selectIn 0.15s cubic-bezier(0.16,1,0.3,1)",
        }}
        {...props}
      >
        {children}
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  );
});
PopoverContent.displayName = "PopoverContent";
