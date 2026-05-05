import { Agent, Position } from "./types";

export interface BackendAgent {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  provider: "openai" | "anthropic";
  model: string;
  tools: string[];
  connections: string[];
}

export interface RoundProposal {
  agent_id: string;
  content: string;
  score: number;
}

export interface RoundDetail {
  round_index: number;
  aggregate: string;
  agreement: number;
  created_at: string;
  proposals: RoundProposal[];
  edges: { from_agent_id: string; to_agent_id: string; weight: number }[];
}

export interface TrialDetail {
  id: string;
  description: string;
  task_prompt: string;
  protocol_name: string;
  final_answer: string;
  stopped_reason: string;
  started_at: string;
  completed_at: string;
  rounds: RoundDetail[];
}

export interface TrialRunResponse {
  trial_id: string;
  answer: string;
  stopped_reason: string;
  rounds: number;
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function listBackendAgents(): Promise<BackendAgent[]> {
  return asJson<BackendAgent[]>(await fetch("/api/agents/"));
}

export async function deleteBackendAgent(id: string): Promise<void> {
  await fetch(`/api/agents/${id}`, { method: "DELETE" });
}

export async function createBackendAgent(agent: Agent): Promise<BackendAgent> {
  const body = {
    name: agent.name || "Agent",
    description: agent.description || "",
    system_prompt:
      agent.systemPrompt ||
      "You are a helpful assistant collaborating with peers to reach a single, concise consensus answer.",
    provider: agent.provider,
    model: agent.model,
    tools: agent.tools,
    connections: agent.connections,
  };
  return asJson<BackendAgent>(
    await fetch("/api/agents/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function updateBackendAgent(agent: Agent): Promise<BackendAgent> {
  const body = {
    name: agent.name,
    description: agent.description,
    system_prompt: agent.systemPrompt,
    provider: agent.provider,
    model: agent.model,
    tools: agent.tools,
    connections: agent.connections,
  };
  return asJson<BackendAgent>(
    await fetch(`/api/agents/${agent.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

function backendToAgent(b: BackendAgent, position: Position): Agent {
  return {
    id: b.id,
    name: b.name,
    description: b.description,
    provider: b.provider,
    model: b.model,
    systemPrompt: b.system_prompt,
    tools: b.tools,
    connections: b.connections,
    position,
  };
}

/** Hook-friendly wrappers used by useCanvasState — return frontend Agent shape. */
export async function fetchAgents(): Promise<Agent[]> {
  const list = await listBackendAgents();
  return list.map((b, i) =>
    backendToAgent(b, {
      x: 220 + (i % 4) * 200,
      y: 200 + Math.floor(i / 4) * 180,
    }),
  );
}

export async function createAgent(a: Agent): Promise<Agent> {
  const created = await createBackendAgent(a);
  return backendToAgent(created, a.position);
}

export async function updateAgent(a: Agent): Promise<Agent> {
  const updated = await updateBackendAgent(a);
  return backendToAgent(updated, a.position);
}

export async function deleteAgentApi(id: string): Promise<void> {
  await deleteBackendAgent(id);
}

export async function runTrial(
  taskPrompt: string,
  agentIds: string[],
  maxRounds = 2,
): Promise<TrialRunResponse> {
  return asJson<TrialRunResponse>(
    await fetch("/api/trials/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_prompt: taskPrompt,
        agent_ids: agentIds,
        max_rounds: maxRounds,
      }),
    }),
  );
}

export async function getTrial(trialId: string): Promise<TrialDetail> {
  return asJson<TrialDetail>(await fetch(`/api/trials/${trialId}`));
}

/**
 * Wipe every agent currently on the backend, then re-create one for each
 * canvas agent. Returns a {canvasId -> backendId} map.
 *
 * The backend uses an in-memory SQLite, so this is the simplest way to keep
 * the canvas UI as the source of truth across runs.
 */
export async function syncAgents(
  canvasAgents: Agent[],
): Promise<Record<string, string>> {
  const existing = await listBackendAgents();
  await Promise.all(existing.map((a) => deleteBackendAgent(a.id)));

  const map: Record<string, string> = {};
  for (const a of canvasAgents) {
    const created = await createBackendAgent(a);
    map[a.id] = created.id;
  }
  return map;
}
