import { Agent, Provider, Source } from "./types";

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

export const PROVIDERS: Record<
  Provider,
  { label: string; models: Array<{ label: string; value: string }> }
> = {
  openai: {
    label: "OpenAI",
    models: [
      { label: "GPT-4o mini", value: "gpt-4o-mini" },
      { label: "GPT-4o", value: "gpt-4o" },
      { label: "GPT-5 nano", value: "gpt-5-nano" },
      { label: "GPT-5 mini", value: "gpt-5-mini" },
      { label: "GPT-5", value: "gpt-5" },
      { label: "GPT-5.4 nano", value: "gpt-5.4-nano" },
      { label: "GPT-5.4 mini", value: "gpt-5.4-mini" },
      { label: "GPT-5.4", value: "gpt-5.4" },
    ],
  },
  anthropic: {
    label: "Anthropic",
    models: [
      { label: "Claude Haiku 4.5", value: "claude-haiku-4-5-20251001" },
      { label: "Claude Sonnet 4.6", value: "claude-sonnet-4-6" },
      { label: "Claude Opus 4.7", value: "claude-opus-4-7" },
    ],
  },
  groq: {
    label: "Groq",
    models: [
      { label: "Llama 3.1 8B Instant", value: "llama-3.1-8b-instant" },
      { label: "Llama 3.3 70B Versatile", value: "llama-3.3-70b-versatile" },
      { label: "GPT OSS 20B", value: "openai/gpt-oss-20b" },
      { label: "GPT OSS 120B", value: "openai/gpt-oss-120b" },
    ],
  },
  gemini: {
    label: "Google Gemini",
    models: [
      { label: "Gemini 2.0 Flash", value: "gemini-2.0-flash" },
      { label: "Gemini 2.5 Flash", value: "gemini-2.5-flash-preview-05-20" },
      { label: "Gemini 2.5 Pro", value: "gemini-2.5-pro-preview-05-06" },
    ],
  },
};

// Must match tool names registered in api/tools/registry.py
export const TOOLS: string[] = ["files"];

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
