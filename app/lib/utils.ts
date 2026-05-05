import { Agent, Source } from "./types";

export const uuid = () => crypto.randomUUID();

export function shortId(id: string): string {
  return id ? id.slice(0, 8) : "";
}

export function clamp(val: number, min: number, max: number): number {
  return Math.min(Math.max(val, min), max);
}

export function timestamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export const PROVIDERS: Record<string, { label: string; models: string[] }> = {
  openai: {
    label: "OpenAI",
    models: ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
  },
  anthropic: {
    label: "Anthropic",
    models: ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-5"],
  },
};

export const TOOLS: string[] = [
  "Web Search",
  "Database Query",
  "Calculator",
  "Document Reader",
  "API Call",
];

export function autoLayout(
  agents: Agent[],
  sources: Source[],
): { agents: Agent[]; sources: Source[] } {
  const all = [...agents, ...sources];
  if (!all.length) return { agents, sources };
  const cols = Math.ceil(Math.sqrt(all.length));
  const positions: Record<string, { x: number; y: number }> = {};
  all.forEach((n, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    positions[n.id] = {
      x: 200 + col * 200 + (row % 2) * 80,
      y: 200 + row * 180,
    };
  });
  return {
    agents: agents.map((a) => ({
      ...a,
      position: positions[a.id] ?? a.position,
    })),
    sources: sources.map((s) => ({
      ...s,
      position: positions[s.id] ?? s.position,
    })),
  };
}
