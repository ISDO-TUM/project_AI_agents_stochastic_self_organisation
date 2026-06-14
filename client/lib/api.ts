/**
 * Typed API client for the backend REST API.
 * Uses relative URLs so all requests are proxied through Next.js rewrites
 * (source: /api/:path* → destination: INTERNAL_API_URL/api/:path*).
 * No NEXT_PUBLIC_ env var needed — the proxy handles both dev and Docker.
 */

import type {
  Agent,
  AgentStat,
  ConsensusMode,
  EdgeStat,
  HistoryMessage,
  HistoryTrial,
  KnowledgeFile,
  LangfuseStats,
  Provider,
  RoundStat,
  Rule,
  TopologyMode,
  TrialSummary,
} from "./types";

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

interface AgentCreatePayload extends AgentPayload {
  id?: string;
}

type AgentUpdate = Partial<AgentPayload>;

// ─── BYOK credential headers ──────────────────────────────────────────────────
// Set by ApiKeysProvider; merged into every request. Kept in memory only.
let llmHeaders: Record<string, string> = {};

export function setLlmHeaders(headers: Record<string, string>): void {
  llmHeaders = headers;
}

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
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const headers: Record<string, string> = { ...llmHeaders, ...extraHeaders };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
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
  const list = await request<AgentOut[]>("GET", "/api/agents");
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

export async function createAgent(
  agent: Agent,
  options: { preserveId?: boolean } = {},
): Promise<Agent> {
  const payload: AgentCreatePayload = toWire(agent);
  if (options.preserveId) payload.id = agent.id;
  const out = await request<AgentOut>("POST", "/api/agents", payload);
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

export async function clearAll(): Promise<void> {
  // The backend requires explicit confirmation for this irreversible bulk wipe.
  await request<void>("DELETE", "/api/agents", undefined, {
    "X-Confirm-Delete": "all",
  });
}

export async function patchAgentTools(
  id: string,
  tools: string[],
): Promise<void> {
  await request<AgentOut>("PATCH", `/api/agents/${id}`, { tools });
}

// ─── Knowledge File endpoints ─────────────────────────────────────────────────

export async function fetchFiles(): Promise<KnowledgeFile[]> {
  return request<KnowledgeFile[]>("GET", "/api/files");
}

export async function createFile(
  name: string,
  content: string,
  id?: string,
): Promise<KnowledgeFile> {
  return request<KnowledgeFile>("POST", "/api/files", { name, content, id });
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

// ─── Models endpoint ─────────────────────────────────────────────────────────

export interface ModelEntry {
  id: string;
  name: string;
  provider: string;
  type: string;
}

export async function fetchModels(): Promise<ModelEntry[]> {
  return request<ModelEntry[]>("GET", "/api/models");
}

// ─── Simulation run ───────────────────────────────────────────────────────────

export interface SimulationResult {
  trialId: string;
  status: string;
  consensus?: string;
}

interface WireSimulationResponse {
  trial_id: string;
  status: string;
}

interface WireHistoryTrial {
  id: string;
  user_prompt: string;
  description: string;
  mode: string | null;
  status: string;
  created_at: string;
  completed_at: string | null;
}

interface WireHistoryMessage {
  id: number;
  trial_id: string;
  trial_description: string;
  round_id: number;
  round_index: number;
  phase: string;
  connection_id: number;
  from_agent_id: string | null;
  from_agent_name: string;
  to_agent_id: string | null;
  to_agent_name: string;
  message_type: string;
  message: string | null;
  created_at: string;
}

function wireToHistoryTrial(w: WireHistoryTrial): HistoryTrial {
  return {
    id: w.id,
    userPrompt: w.user_prompt,
    description: w.description,
    mode: w.mode,
    status: w.status,
    createdAt: w.created_at,
    completedAt: w.completed_at,
  };
}

function wireToHistoryMessage(w: WireHistoryMessage): HistoryMessage {
  return {
    id: w.id,
    trialId: w.trial_id,
    trialDescription: w.trial_description,
    roundId: w.round_id,
    roundIndex: w.round_index,
    phase: w.phase,
    connectionId: w.connection_id,
    fromAgentId: w.from_agent_id,
    fromAgentName: w.from_agent_name,
    toAgentId: w.to_agent_id,
    toAgentName: w.to_agent_name,
    messageType: w.message_type,
    message: w.message,
    createdAt: w.created_at,
  };
}

export async function runSimulation(
  prompt: string,
  options: {
    rounds?: number;
    mode?: ConsensusMode;
    agentContext?: Record<string, string>;
    ruleset?: string;
    topology?: TopologyMode;
    fanout?: number;
  } = {},
): Promise<SimulationResult> {
  const {
    rounds = 3,
    mode = "broadcast_no_consensus",
    agentContext,
    ruleset,
    topology = "static",
    fanout = 3,
  } = options;
  const data = await request<WireSimulationResponse>(
    "POST",
    "/api/simulation/run",
    {
      prompt,
      rounds,
      mode,
      topology,
      fanout,
      ...(agentContext && { agent_context: agentContext }),
      ...(ruleset && ruleset.trim() && { ruleset }),
    },
  );
  return {
    trialId: data.trial_id,
    status: data.status,
  };
}

// ─── History endpoints ───────────────────────────────────────────────────────

export async function fetchHistoryTrials(): Promise<HistoryTrial[]> {
  const rows = await request<WireHistoryTrial[]>("GET", "/api/history/trials");
  return rows.map(wireToHistoryTrial);
}

export async function fetchHistoryTrial(
  trialId: string,
): Promise<HistoryTrial> {
  const row = await request<WireHistoryTrial>(
    "GET",
    `/api/history/trials/${trialId}`,
  );
  return wireToHistoryTrial(row);
}

export async function fetchHistoryMessages(filters: {
  trialId?: string;
  roundId?: number;
  agentId?: string;
  messageType?: string;
  afterId?: number;
}): Promise<HistoryMessage[]> {
  const params = new URLSearchParams();
  if (filters.trialId) params.set("trial_id", filters.trialId);
  if (filters.roundId != null) params.set("round_id", String(filters.roundId));
  if (filters.agentId) params.set("agent_id", filters.agentId);
  if (filters.messageType) params.set("message_type", filters.messageType);
  if (filters.afterId != null) params.set("after_id", String(filters.afterId));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const rows = await request<WireHistoryMessage[]>(
    "GET",
    `/api/history/messages${suffix}`,
  );
  return rows.map(wireToHistoryMessage);
}

// ─── Statistics endpoints ───────────────────────────────────────────────────

interface WireTrialSummary {
  trial_id: string;
  user_prompt: string;
  description: string;
  mode: string | null;
  status: string;
  created_at: string;
  round_count: number;
  agent_count: number;
  total_messages: number;
  total_edges: number;
  message_type_counts: Record<string, number>;
}

interface WireAgentStat {
  agent_id: string;
  agent_name: string;
  messages_sent: number;
  messages_received: number;
  out_degree: number;
  in_degree: number;
  tool_invocations: number;
}

interface WireEdgeStat {
  from_agent_id: string;
  from_agent_name: string;
  to_agent_id: string;
  to_agent_name: string;
  message_count: number;
}

interface WireRoundStat {
  round_id: number;
  round_index: number;
  phase: string;
  message_count: number;
  active_edge_count: number;
}

interface WireLangfuseSummary {
  trial_id: string;
  trace_count: number;
  generation_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  average_latency_ms: number;
  slowest_agent_name: string | null;
  slowest_model: string | null;
}

interface WireLangfuseAgentStat {
  agent_id: string;
  agent_name: string;
  generation_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  average_latency_ms: number;
}

interface WireLangfuseModelStat {
  model: string;
  generation_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  average_latency_ms: number;
}

interface WireLangfuseRoundStat {
  round_index: number;
  phase: string;
  generation_count: number;
  total_tokens: number;
  total_cost: number;
  average_latency_ms: number;
}

interface WireLangfuseStats {
  summary: WireLangfuseSummary;
  agents: WireLangfuseAgentStat[];
  models: WireLangfuseModelStat[];
  rounds: WireLangfuseRoundStat[];
  available: boolean;
  message: string | null;
}

export async function fetchTrialSummary(
  trialId: string,
): Promise<TrialSummary> {
  const r = await request<WireTrialSummary>(
    "GET",
    `/api/statistics/trials/${trialId}/summary`,
  );
  return {
    trialId: r.trial_id,
    userPrompt: r.user_prompt,
    description: r.description,
    mode: r.mode,
    status: r.status,
    createdAt: r.created_at,
    roundCount: r.round_count,
    agentCount: r.agent_count,
    totalMessages: r.total_messages,
    totalEdges: r.total_edges,
    messageTypeCounts: r.message_type_counts,
  };
}

export async function fetchAgentStats(trialId: string): Promise<AgentStat[]> {
  const rows = await request<WireAgentStat[]>(
    "GET",
    `/api/statistics/trials/${trialId}/agents`,
  );
  return rows.map((r) => ({
    agentId: r.agent_id,
    agentName: r.agent_name,
    messagesSent: r.messages_sent,
    messagesReceived: r.messages_received,
    outDegree: r.out_degree,
    inDegree: r.in_degree,
    toolInvocations: r.tool_invocations,
  }));
}

export async function fetchEdgeStats(trialId: string): Promise<EdgeStat[]> {
  const rows = await request<WireEdgeStat[]>(
    "GET",
    `/api/statistics/trials/${trialId}/edges`,
  );
  return rows.map((r) => ({
    fromAgentId: r.from_agent_id,
    fromAgentName: r.from_agent_name,
    toAgentId: r.to_agent_id,
    toAgentName: r.to_agent_name,
    messageCount: r.message_count,
  }));
}

export async function fetchRoundStats(trialId: string): Promise<RoundStat[]> {
  const rows = await request<WireRoundStat[]>(
    "GET",
    `/api/statistics/trials/${trialId}/timeline`,
  );
  return rows.map((r) => ({
    roundId: r.round_id,
    roundIndex: r.round_index,
    phase: r.phase,
    messageCount: r.message_count,
    activeEdgeCount: r.active_edge_count,
  }));
}

export async function fetchLangfuseStats(
  trialId: string,
): Promise<LangfuseStats> {
  const r = await request<WireLangfuseStats>(
    "GET",
    `/api/statistics/trials/${trialId}/langfuse`,
  );
  return {
    summary: {
      trialId: r.summary.trial_id,
      traceCount: r.summary.trace_count,
      generationCount: r.summary.generation_count,
      inputTokens: r.summary.input_tokens,
      outputTokens: r.summary.output_tokens,
      totalTokens: r.summary.total_tokens,
      totalCost: r.summary.total_cost,
      averageLatencyMs: r.summary.average_latency_ms,
      slowestAgentName: r.summary.slowest_agent_name,
      slowestModel: r.summary.slowest_model,
    },
    agents: r.agents.map((row) => ({
      agentId: row.agent_id,
      agentName: row.agent_name,
      generationCount: row.generation_count,
      inputTokens: row.input_tokens,
      outputTokens: row.output_tokens,
      totalTokens: row.total_tokens,
      totalCost: row.total_cost,
      averageLatencyMs: row.average_latency_ms,
    })),
    models: r.models.map((row) => ({
      model: row.model,
      generationCount: row.generation_count,
      inputTokens: row.input_tokens,
      outputTokens: row.output_tokens,
      totalTokens: row.total_tokens,
      totalCost: row.total_cost,
      averageLatencyMs: row.average_latency_ms,
    })),
    rounds: r.rounds.map((row) => ({
      roundIndex: row.round_index,
      phase: row.phase,
      generationCount: row.generation_count,
      totalTokens: row.total_tokens,
      totalCost: row.total_cost,
      averageLatencyMs: row.average_latency_ms,
    })),
    available: r.available,
    message: r.message,
  };
}

// ─── Rules ───────────────────────────────────────────────────────────────────

export async function fetchRules(): Promise<Rule[]> {
  return request<Rule[]>("GET", "/api/rules");
}
