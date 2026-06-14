export type Provider = "openai" | "anthropic" | "groq" | "gemini";
export type SourceType = "text" | "document" | "dataset";
export type SimStepType = "system" | "agent-to-agent" | "tool";

export type ConsensusMode =
  | "broadcast_no_consensus"
  | "weighted_opinion_pooling"
  | "plurality_voting"
  | "bidding";

export type TopologyMode = "static" | "dynamic";

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
  /** Raw server-side message_type (e.g. "bidding_bid"). Used by views that
   *  need to parse the message body (bidding board) rather than render a label. */
  messageType?: string;
  roundIndex?: number;
  target?: string;
  nodeId?: string;
  fromId?: string;
  toId?: string;
  /** lucide-react icon name overriding the type-derived default. */
  icon?: string;
  /** True for a connection formed at runtime (dynamic "phone-book") rather than
   *  one present in the static seed graph. */
  dynamic?: boolean;
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

export interface ConversationTurn {
  prompt: string;
  mode: ConsensusMode;
  answer: string | null;
}

export interface TrialSummary {
  trialId: string;
  userPrompt: string;
  description: string;
  mode: ConsensusMode | string | null;
  status: string;
  createdAt: string;
  roundCount: number;
  agentCount: number;
  totalMessages: number;
  totalEdges: number;
  messageTypeCounts: Record<string, number>;
}

export interface AgentStat {
  agentId: string;
  agentName: string;
  messagesSent: number;
  messagesReceived: number;
  outDegree: number;
  inDegree: number;
  toolInvocations: number;
}

export interface EdgeStat {
  fromAgentId: string;
  fromAgentName: string;
  toAgentId: string;
  toAgentName: string;
  messageCount: number;
}

export interface RoundStat {
  roundId: number;
  roundIndex: number;
  phase: string;
  messageCount: number;
  activeEdgeCount: number;
}

export interface LangfuseSummary {
  trialId: string;
  traceCount: number;
  generationCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCost: number;
  averageLatencyMs: number;
  slowestAgentName: string | null;
  slowestModel: string | null;
}

export interface LangfuseAgentStat {
  agentId: string;
  agentName: string;
  generationCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCost: number;
  averageLatencyMs: number;
}

export interface LangfuseModelStat {
  model: string;
  generationCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCost: number;
  averageLatencyMs: number;
}

export interface LangfuseRoundStat {
  roundIndex: number;
  phase: string;
  generationCount: number;
  totalTokens: number;
  totalCost: number;
  averageLatencyMs: number;
}

export interface LangfuseStats {
  summary: LangfuseSummary;
  agents: LangfuseAgentStat[];
  models: LangfuseModelStat[];
  rounds: LangfuseRoundStat[];
  available: boolean;
  message: string | null;
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
