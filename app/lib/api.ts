/**
 * Typed API client for the backend REST API.
 * Uses relative URLs so all requests are proxied through Next.js rewrites
 * (source: /api/:path* → destination: INTERNAL_API_URL/api/:path*).
 * No NEXT_PUBLIC_ env var needed — the proxy handles both dev and Docker.
 */

import type { Agent, KnowledgeFile, Provider, SimStep } from "./types";

// ─── Wire types ──────────────────────────────────────────────────────────────

interface AgentOut {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  provider: Provider;
  model: string;
  tools: string[];
  connections: string[];
}

interface AgentPayload {
  name: string;
  description: string;
  system_prompt: string;
  provider: Provider;
  model: string;
  tools: string[];
  connections: string[];
}

type AgentUpdate = Partial<AgentPayload>;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fromWire(a: AgentOut, position = { x: 220, y: 200 }): Agent {
  return {
    id: a.id,
    name: a.name,
    description: a.description,
    systemPrompt: a.system_prompt,
    provider: a.provider,
    model: a.model,
    tools: a.tools,
    connections: a.connections,
    position,
  };
}

function toWire(a: Agent): AgentPayload {
  return {
    name: a.name,
    description: a.description,
    system_prompt: a.systemPrompt,
    provider: a.provider,
    model: a.model,
    tools: a.tools,
    connections: a.connections,
  };
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
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

export async function fetchAgents(
  positionMap?: Record<string, { x: number; y: number }>,
): Promise<Agent[]> {
  const list = await request<AgentOut[]>("GET", "/api/agents/");
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

export async function createAgent(agent: Agent): Promise<Agent> {
  const out = await request<AgentOut>("POST", "/api/agents/", toWire(agent));
  return fromWire(out, agent.position);
}

export async function updateAgent(agent: Agent): Promise<Agent> {
  const out = await request<AgentOut>(
    "PATCH",
    `/api/agents/${agent.id}`,
    toWire(agent) satisfies AgentUpdate,
  );
  return fromWire(out, agent.position);
}

export async function deleteAgentApi(id: string): Promise<void> {
  await request<void>("DELETE", `/api/agents/${id}`);
}

export async function patchAgentTools(
  id: string,
  tools: string[],
): Promise<void> {
  await request<AgentOut>("PATCH", `/api/agents/${id}`, { tools });
}

// ─── Knowledge File endpoints ─────────────────────────────────────────────────

export async function fetchFiles(): Promise<KnowledgeFile[]> {
  return request<KnowledgeFile[]>("GET", "/api/files/");
}

export async function createFile(
  name: string,
  content: string,
  id?: string,
): Promise<KnowledgeFile> {
  return request<KnowledgeFile>("POST", "/api/files/", { name, content, id });
}

export async function updateFileContent(
  id: string,
  name: string,
  content: string,
): Promise<KnowledgeFile> {
  return request<KnowledgeFile>("PUT", `/api/files/${id}`, { name, content });
}

export async function deleteFileApi(id: string): Promise<void> {
  await request<void>("DELETE", `/api/files/${id}`);
}

export async function fetchAgentFiles(
  agentId: string,
): Promise<KnowledgeFile[]> {
  return request<KnowledgeFile[]>("GET", `/api/agents/${agentId}/files`);
}

export async function attachFile(
  agentId: string,
  fileId: string,
): Promise<void> {
  await request<void>("POST", `/api/agents/${agentId}/files/${fileId}`);
}

export async function detachFile(
  agentId: string,
  fileId: string,
): Promise<void> {
  await request<void>("DELETE", `/api/agents/${agentId}/files/${fileId}`);
}

// ─── Agent run ────────────────────────────────────────────────────────────────

interface AgentRunResponse {
  agent_id: string;
  response: string;
  tools_used: Array<{
    name: string;
    input: Record<string, unknown>;
    output: string;
  }>;
}

export async function runAgent(
  agentId: string,
  prompt: string,
): Promise<AgentRunResponse> {
  return request<AgentRunResponse>("POST", `/api/agents/${agentId}/run`, {
    prompt,
  });
}

// ─── Simulation run ───────────────────────────────────────────────────────────

interface WireSimStep {
  id: string;
  ts: string;
  label: string;
  msg: string;
  type: SimStep["type"];
  target?: string | null;
  node_id?: string | null;
  from_id?: string | null;
  to_id?: string | null;
}

function wireToSimStep(w: WireSimStep): SimStep {
  return {
    id: w.id,
    ts: w.ts,
    label: w.label,
    msg: w.msg,
    type: w.type,
    ...(w.target != null && { target: w.target }),
    ...(w.node_id != null && { nodeId: w.node_id }),
    ...(w.from_id != null && { fromId: w.from_id }),
    ...(w.to_id != null && { toId: w.to_id }),
  };
}

export async function runSimulation(
  prompt: string,
  rounds = 1,
): Promise<SimStep[]> {
  const data = await request<{ steps: WireSimStep[] }>(
    "POST",
    "/api/simulation/run",
    { prompt, rounds },
  );
  return data.steps.map(wireToSimStep);
}
