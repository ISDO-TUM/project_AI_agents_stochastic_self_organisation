const PATHS: Record<string, string[]> = {
  Bot: [
    "M12 8V4",
    "M8 8h8",
    "M4 14a8 8 0 0016 0v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2z",
    "M9 17v1",
    "M15 17v1",
  ],
  FileText: [
    "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z",
    "M14 2v6h6",
    "M16 13H8",
    "M16 17H8",
    "M10 9H8",
  ],
  Trash2: [
    "M3 6h18",
    "M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6",
    "M10 11v6",
    "M14 11v6",
    "M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2",
  ],
  X: ["M18 6L6 18", "M6 6l12 12"],
  Sun: [
    "M12 1v2",
    "M12 21v2",
    "M4.22 4.22l1.42 1.42",
    "M18.36 18.36l1.42 1.42",
    "M1 12h2",
    "M21 12h2",
    "M4.22 19.78l1.42-1.42",
    "M18.36 5.64l1.42-1.42",
    "M12 5a7 7 0 100 14A7 7 0 0012 5z",
  ],
  Moon: ["M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"],
  Send: ["M22 2L11 13", "M22 2L15 22l-4-9-9-4 20-7z"],
  Download: [
    "M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4",
    "M7 10l5 5 5-5",
    "M12 15V3",
  ],
  Upload: [
    "M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4",
    "M17 8l-5-5-5 5",
    "M12 3v12",
  ],
  Shuffle: ["M16 3h5v5", "M4 20L21 3", "M21 16v5h-5", "M15 15l6 6", "M4 4l5 5"],
  Settings2: [
    "M20 7H9",
    "M20 12H9",
    "M20 17H9",
    "M5 7v.01",
    "M5 12v.01",
    "M5 17v.01",
  ],
  Maximize2: ["M15 3h6v6", "M9 21H3v-6", "M21 3l-7 7", "M3 21l7-7"],
  Minimize2: ["M4 14h6v6", "M20 10h-6V4", "M14 10l7-7", "M3 21l7-7"],
  Square: ["M3 3h18v18H3z"],
  ChevronLeft: ["M15 18l-6-6 6-6"],
  ChevronRight: ["M9 18l6-6-6-6"],
  Network: [
    "M9 3H5a2 2 0 00-2 2v4",
    "M15 3h4a2 2 0 012 2v4",
    "M9 21H5a2 2 0 01-2-2v-4",
    "M15 21h4a2 2 0 002-2v-4",
    "M9 3v18",
    "M15 3v18",
    "M3 9h18",
    "M3 15h18",
  ],
  Wrench: [
    "M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z",
  ],
  Globe: [
    "M12 2a10 10 0 100 20A10 10 0 0012 2z",
    "M2 12h20",
    "M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z",
  ],
  Database: [
    "M12 2C8.13 2 5 3.79 5 6v12c0 2.21 3.13 4 7 4s7-1.79 7-4V6c0-2.21-3.13-4-7-4z",
    "M5 12c0 2.21 3.13 4 7 4s7-1.79 7-4",
    "M5 6c0 2.21 3.13 4 7 4s7-1.79 7-4",
  ],
  Calculator: [
    "M4 2h16a2 2 0 012 2v16a2 2 0 01-2 2H4a2 2 0 01-2-2V4a2 2 0 012-2z",
    "M8 6h.01",
    "M12 6h.01",
    "M16 6h.01",
    "M8 10h.01",
    "M12 10h.01",
    "M16 10h.01",
    "M8 14h8",
    "M8 18h8",
  ],
  Zap: ["M13 2L3 14h9l-1 8 10-12h-9l1-8z"],
  Check: ["M20 6L9 17l-5-5"],
  AlertCircle: [
    "M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10z",
    "M12 8v4",
    "M12 16h.01",
  ],
  Plus: ["M12 5v14", "M5 12h14"],
  Eye: [
    "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z",
    "M12 9a3 3 0 100 6 3 3 0 000-6z",
  ],
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
  const paths = PATHS[name];
  if (!paths) return null;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, display: "block" }}
    >
      {paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}

export const TOOL_ICON: Record<string, string> = {
  "Web Search": "Globe",
  "Database Query": "Database",
  Calculator: "Calculator",
  "Document Reader": "FileText",
  "API Call": "Zap",
};
