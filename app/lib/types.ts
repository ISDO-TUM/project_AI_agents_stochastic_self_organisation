export type Provider = "openai" | "anthropic" | "groq";
export type SourceType = "text" | "document";
export type SimStepType =
  | "system"
  | "agent-to-agent"
  | "tool"
  | "agent-to-source";

export interface Position {
  x: number;
  y: number;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  provider: Provider;
  model: string;
  systemPrompt: string;
  tools: string[];
  connections: string[];
  position: Position;
}

export interface Source {
  id: string;
  name: string;
  type: SourceType;
  content: string;
  position: Position;
}

export interface KnowledgeFile {
  id: string;
  name: string;
  content: string;
}

export interface Edge {
  id: string;
  from: string;
  to: string;
}

export interface SimStep {
  id: string;
  ts: string;
  label: string;
  msg: string;
  type: SimStepType;
  target?: string;
  nodeId?: string;
  fromId?: string;
  toId?: string;
}

export interface AnimatedParticle {
  id: string;
  from: string;
  to: string;
  dur: number;
  delay: number;
}

export interface Tweaks {
  nodeSize: number;
  edgeWidth: number;
  gridDensity: number;
  showGrid: boolean;
  showOrbs: boolean;
  particleSpeed: number;
  showPulse: boolean;
  accentColor: string;
}

export interface CanvasState {
  agents: Agent[];
  sources: Source[];
  edges: Edge[];
}

export type CanvasAction =
  | { type: "ADD_AGENT"; agent: Agent }
  | { type: "UPDATE_AGENT"; agent: Agent }
  | { type: "DELETE_AGENT"; id: string }
  | { type: "ADD_SOURCE"; source: Source }
  | { type: "UPDATE_SOURCE"; source: Source }
  | { type: "DELETE_SOURCE"; id: string }
  | { type: "MOVE_NODE"; id: string; position: Position }
  | { type: "ADD_EDGE"; edge: Edge }
  | { type: "DELETE_EDGE"; id: string }
  | { type: "CLEAR" }
  | { type: "LOAD"; state: CanvasState }
  | { type: "AUTO_LAYOUT" };

// ── ECSAS swarm types ─────────────────────────────────────────────────────

export type SwarmSimStepType =
  | SimStepType
  | "bid"
  | "abstain"
  | "bb-post"
  | "bb-cite"
  | "bb-vote"
  | "bb-promote"
  | "bb-delete"
  | "bb-mention"
  | "amendment"
  | "amendment-approved"
  | "amendment-rejected"
  | "convergence";

export interface ThreadInfo {
  id: string;
  contract_id: string;
  run_id: string;
  title: string;
  description: string;
  required_expertise: string[];
  complexity: "low" | "medium" | "high";
  created_at: string;
}

export interface ConfirmedEntry {
  id: string;
  run_id: string;
  thread_id: string;
  source_draft_id: string | null;
  content: string;
  entry_type: "anchor" | "finding" | "system";
  citation_count: number;
  round_confirmed: number;
  created_at: string;
}

export interface DraftEntry {
  id: string;
  run_id: string;
  thread_id: string;
  round: number;
  author_id: string;
  author_name: string;
  entry_type: "proposal" | "reply" | "vote" | "system";
  content: string;
  reply_to: string | null;
  mention_agents: string[];
  is_visible: boolean;
  deleted_at: string | null;
  last_cited_round: number;
  citation_count: number;
  created_at: string;
  children: DraftEntry[];
}

export interface BlackboardState {
  threads: ThreadInfo[];
  confirmed: ConfirmedEntry[];
  draft: DraftEntry[];
  loading: boolean;
  error: string | null;
}
