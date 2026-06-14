import { LucideProps } from "lucide-react";
import * as Icons from "lucide-react";

// Keyed by registered tool name (see TOOLS in lib/utils.ts)
export const TOOL_ICON: Record<string, string> = {
  files: "FileText",
  table_query: "Table2",
  table_mutate: "Table2",
};

interface LIconProps {
  name: string;
  size?: number;
  color?: string;
  sw?: number;
}

export function LIcon({
  name,
  size = 15,
  color = "currentColor",
  sw = 1.85,
}: LIconProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Icon = (Icons as Record<string, any>)[name] as
    | React.ComponentType<LucideProps>
    | undefined;
  if (!Icon) return null;
  return (
    <Icon
      size={size}
      color={color}
      strokeWidth={sw}
      style={{ flexShrink: 0, display: "block" }}
    />
  );
}
