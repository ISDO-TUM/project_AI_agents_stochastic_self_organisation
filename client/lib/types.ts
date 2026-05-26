export type Provider = "openai" | "anthropic" | "groq" | "gemini";
export type SourceType = "text" | "document";
export type SimStepType =
  | "system"
  | "agent-to-agent"
  | "tool"
  | "agent-to-source";

export type ConsensusMode =
  | "broadcast_no_consensus"
  | "weighted_opinion_pooling"
  | "plurality_voting"
  | "bidding";

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
  roundIndex?: number;
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
  selectedRules?: string[];
}

export interface Rule {
  id: string;
  label: string;
  instruction: string;
  default?: boolean;
}

export interface HistoryTrial {
  id: string;
  userPrompt: string;
  description: string;
  mode: string | null;
  status: string;
  createdAt: string;
  completedAt: string | null;
}

export interface HistoryMessage {
  id: number;
  trialId: string;
  trialDescription: string;
  roundId: number;
  roundIndex: number;
  phase: string;
  connectionId: number;
  fromAgentId: string | null;
  fromAgentName: string;
  toAgentId: string | null;
  toAgentName: string;
  messageType: string;
  message: string | null;
  createdAt: string;
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
