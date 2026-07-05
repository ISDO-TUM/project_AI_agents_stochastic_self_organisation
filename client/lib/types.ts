export type Provider = "openai" | "anthropic" | "groq" | "gemini";
export type SourceType = "text" | "document" | "dataset";
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
  /** Agent ids that should receive this file when the swarm starts. */
  agentIds?: string[];
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
  /** Results of the last completed Market Hive run, embedded on export so
   *  runs can be saved and compared later. Ignored on import. */
  swarmResults?: SwarmRunExport;
}

/** Snapshot of a completed Market Hive run for the exported canvas JSON. */
export interface SwarmRunExport {
  runId: string;
  trialId: string | null;
  experimentId: string | null;
  prompt: string | null;
  exportedAt: string;
  finalAnswer: string | null;
  threads: ThreadInfo[];
  confirmed: ConfirmedEntry[];
  draft: DraftEntry[];
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

// ─── Experiments ─────────────────────────────────────────────────────────────

export interface ExperimentListItem {
  id: string;
  description: string;
  trialCount: number;
  createdAt: string;
  mode: string | null;
  userPrompt: string | null;
}

export interface ExperimentSummary {
  experimentId: string;
  description: string;
  mode: string | null;
  userPrompt: string | null;
  trialCount: number;
  trialIds: string[];
  avgRoundCount: number;
  avgAgentCount: number;
  avgTotalMessages: number;
  avgTotalEdges: number;
  messageTypeCounts: Record<string, number>;
}

export interface ExperimentAgentStat {
  agentId: string;
  agentName: string;
  avgMessagesSent: number;
  avgMessagesReceived: number;
  avgOutDegree: number;
  avgInDegree: number;
  avgToolInvocations: number;
}

export interface ExperimentEdgeStat {
  fromAgentId: string;
  fromAgentName: string;
  toAgentId: string;
  toAgentName: string;
  avgMessageCount: number;
}

export interface ExperimentRoundStat {
  roundIndex: number;
  phase: string;
  avgMessageCount: number;
  avgActiveEdgeCount: number;
}

export interface ExperimentLangfuseSummary {
  experimentId: string;
  trialCount: number;
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

export interface ExperimentLangfuseStats {
  summary: ExperimentLangfuseSummary;
  agents: LangfuseAgentStat[];
  models: LangfuseModelStat[];
  rounds: LangfuseRoundStat[];
  available: boolean;
  message: string | null;
}

// ─── Consistency ─────────────────────────────────────────────────────────────

export interface PairwiseSimilarity {
  trialIdA: string;
  trialIdB: string;
  cosineSimilarity: number;
}

export interface ConsistencyReport {
  experimentId: string;
  trialCount: number;
  trialsWithAnswers: number;
  avgCosineSimilarity: number | null;
  pairwiseScores: PairwiseSimilarity[];
  aiSummary: string | null;
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
  /** Contestable consensus: a confirmed entry may be disputed (contested),
   *  re-affirmed back to confirmed, or retracted at termination. Optional so
   *  entries from before the feature (or dummy fixtures) default to confirmed. */
  status?: "confirmed" | "contested" | "retracted";
  /** Multi-turn contract sessions: set on a carried-forward anchor to the run
   *  that originally ratified it. No UI renders this yet (API + mechanics only). */
  origin_run_id?: string | null;
}

/** The takers' approve/revise vote on the synthesised final answer
 *  (ratified synthesis). Null when the run predates the feature or shipped
 *  with no takers left to ratify. */
export interface Ratification {
  approved: boolean;
  round: 1 | 2;
  approvals: number;
  voters: number;
  objections: string[];
}

export interface Citer {
  agentName: string;
  round: number;
}

export type AgentSwarmRole = "taker" | "observer";

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
  /** File names the author consulted (via the files() tool) while producing
   *  this entry. Populated by the real backend at post time; the dummy
   *  pipeline sets sample values on a couple of fixture entries. */
  documents_used?: string[];
  is_visible: boolean;
  deleted_at: string | null;
  last_cited_round: number;
  citation_count: number;
  created_at: string;
  children: DraftEntry[];
  citers?: Citer[];
}

export interface BlackboardState {
  threads: ThreadInfo[];
  confirmed: ConfirmedEntry[];
  draft: DraftEntry[];
  // Replies streamed in before their parent (concurrent turns complete, and
  // stream to the client, in completion order rather than DB-write order) —
  // held here and retried on every new arrival instead of rendered orphaned.
  pendingReplies: DraftEntry[];
  loading: boolean;
  error: string | null;
}

export interface AgentTrustEntry {
  domain: string;
  trust_score: number;
  runs_participated: number;
  updated_at: string;
}
