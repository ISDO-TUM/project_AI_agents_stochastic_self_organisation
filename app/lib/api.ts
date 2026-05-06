/**
 * Typed API client for the backend REST API.
 * Base URL is read from NEXT_PUBLIC_API_URL (defaults to http://localhost:8000).
 *
 * Wire-format types (snake_case, tools/connections as JSON strings) are kept
 * internal. Public functions accept/return the frontend Agent type.
 */

import type { Agent, Provider } from "./types";

const BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

// ─── Wire types ──────────────────────────────────────────────────────────────

interface AgentOut {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  provider: Provider;
  model: string;
  tools: string; // JSON array string
  connections: string; // JSON array string
}

interface AgentCreate {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  provider: Provider;
  model: string;
  tools: string;
  connections: string;
}

type AgentUpdate = Partial<Omit<AgentCreate, "id">>;

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Parse JSON safely; falls back to empty array on failure.
 */
function parseArr(v: string | string[]): string[] {
  if (Array.isArray(v)) return v;
  try {
    const parsed = JSON.parse(v);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Convert a wire AgentOut into the frontend Agent type.
 * `position` is canvas-only and not stored in the DB; callers may override it.
 */
function fromWire(a: AgentOut, position = { x: 220, y: 200 }): Agent {
  return {
    id: a.id,
    name: a.name,
    description: a.description,
    systemPrompt: a.system_prompt,
    provider: a.provider,
    model: a.model,
    tools: parseArr(a.tools),
    connections: parseArr(a.connections),
    position,
  };
}

/**
 * Convert a frontend Agent into the wire AgentCreate shape.
 * `position` is omitted — it is canvas-only and not persisted.
 */
function toWire(a: Agent): AgentCreate {
  return {
    id: a.id,
    name: a.name,
    description: a.description,
    system_prompt: a.systemPrompt,
    provider: a.provider,
    model: a.model,
    tools: JSON.stringify(a.tools),
    connections: JSON.stringify(a.connections),
  };
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${method} ${path} → ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Agent endpoints ──────────────────────────────────────────────────────────

/**
 * GET /agents — returns all agents.
 * Pass an existing position map to restore canvas positions across reloads.
 */
export async function fetchAgents(
  positionMap?: Record<string, { x: number; y: number }>,
): Promise<Agent[]> {
  const list = await request<AgentOut[]>("GET", "/agents");
  return list.map((a, i) =>
    fromWire(
      a,
      positionMap?.[a.id] ?? {
        x: 180 + (i % 4) * 220,
        y: 160 + Math.floor(i / 4) * 180,
      },
    ),
  );
}

/**
 * POST /agents — create a new agent. Returns the created agent with its ID.
 */
export async function createAgent(agent: Agent): Promise<Agent> {
  const out = await request<AgentOut>("POST", "/agents", toWire(agent));
  return fromWire(out, agent.position);
}

/**
 * PATCH /agents/{id} — update an existing agent.
 */
export async function updateAgent(agent: Agent): Promise<Agent> {
  const { id, ...rest } = toWire(agent);
  const out = await request<AgentOut>(
    "PATCH",
    `/agents/${id}`,
    rest satisfies AgentUpdate,
  );
  return fromWire(out, agent.position);
}

/**
 * DELETE /agents/{id} — delete an agent. Returns void (204).
 */
export async function deleteAgentApi(id: string): Promise<void> {
  await request<void>("DELETE", `/agents/${id}`);
}
