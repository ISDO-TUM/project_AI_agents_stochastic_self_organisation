import {
  Agent,
  AgentSwarmRole,
  ConfirmedEntry,
  DraftEntry,
  ThreadInfo,
} from "./types";

export interface DummySwarmConfig {
  takers: number;
  rounds: number;
}

export interface DummyAgentInfo {
  id: string;
  name: string;
  provider: string;
  model: string;
  role: AgentSwarmRole;
}

export type DummyEvent =
  | { kind: "post"; delay: number; entry: DraftEntry }
  | {
      kind: "cite";
      delay: number;
      entryId: string;
      citerName: string;
      round: number;
    }
  | { kind: "promote"; delay: number; confirmed: ConfirmedEntry }
  | { kind: "delete"; delay: number; entryId: string };

export interface DummyRunFixture {
  runId: string;
  threads: ThreadInfo[];
  agents: DummyAgentInfo[];
  events: DummyEvent[];
  trustVectors: Record<
    string,
    { domain: string; trust_score: number; runs_participated: number }[]
  >;
}

const SYNTHETIC_AGENTS: Omit<DummyAgentInfo, "role">[] = [
  {
    id: "dummy-alpha",
    name: "Alpha",
    provider: "anthropic",
    model: "claude-sonnet-4-6",
  },
  { id: "dummy-beta", name: "Beta", provider: "openai", model: "gpt-4o" },
  {
    id: "dummy-gamma",
    name: "Gamma",
    provider: "anthropic",
    model: "claude-haiku-4-5",
  },
  {
    id: "dummy-delta",
    name: "Delta",
    provider: "gemini",
    model: "gemini-2.5-pro",
  },
  {
    id: "dummy-sigma",
    name: "Sigma",
    provider: "groq",
    model: "llama-3.3-70b",
  },
];

const PROPOSALS = [
  "The penalty clause in §4.2 is unenforceable under EU law: the liquidated damages cap (€50k) is disproportionate to the actual estimated loss range (€200k–€800k). DCF analysis confirms.",
  "Counter-read: §4.2's cap was negotiated against a force-majeure carve-out in §4.5, so the two clauses should be read together — the cap is reasonable once that's accounted for.",
  "Termination notice period (§7.1) is 30 days, but the supplier's own SLA promises 45-day transition support — there's an internal inconsistency to flag before signing.",
  "Indexation in §3.3 ties pricing to a discontinued benchmark (LIBOR). Needs a fallback clause to SOFR or the pricing mechanism is void from 2024 onward.",
];

const REPLIES = [
  "Agreed — the DCF figures in the contract attachment back this up directly.",
  "Worth flagging to the counterparty before round 2 closes.",
  "Can we get a second source on that estimated loss range?",
  "{mention}can you verify the discount rate used here?",
  "This changes my confidence on the termination clause too.",
];

const REPLIES_TO_REPLIES = [
  "To push back on that: the SOFR transition was already addressed in the side letter from Feb 2024 — does that change your read?",
  "Exactly — if the DCF rate assumption drifts by 2%, the enforceability argument inverts. Have you modelled that scenario?",
  "That said, the 45-day SLA clause predates the amended annex, so the inconsistency may be intentional. Worth confirming with the counterparty.",
  "I'd flag this as unresolved rather than confirmed — a second source isn't in the data room yet.",
  "Counter: the force-majeure reading only holds if §4.5(b)'s material-breach threshold is met, which we haven't defined yet.",
];

function makeId(prefix: string, n: number): string {
  return `${prefix}-${n}`;
}

export function generateDummyRun(
  config: DummySwarmConfig,
  existingAgents: Agent[],
): DummyRunFixture {
  const takers = Math.min(5, Math.max(2, config.takers));
  const rounds = Math.min(5, Math.max(2, config.rounds));
  const runId = `dummy-${Date.now()}`;
  const nowIso = new Date().toISOString();

  const pool: DummyAgentInfo[] =
    existingAgents.length >= 2
      ? existingAgents.slice(0, 5).map((a, i) => ({
          id: a.id,
          name: a.name,
          provider: a.provider,
          model: a.model,
          role: i < takers ? "taker" : "observer",
        }))
      : SYNTHETIC_AGENTS.map((a, i) => ({
          ...a,
          role: i < takers ? "taker" : "observer",
        }));

  const agents = pool.slice(
    0,
    Math.max(takers, Math.min(pool.length, takers + 2)),
  );
  const takerAgents = agents.filter((a) => a.role === "taker");

  const threadIds = ["dummy-thread-1", "dummy-thread-2"];
  const threads: ThreadInfo[] = [
    {
      id: threadIds[0],
      contract_id: "dummy-contract",
      run_id: runId,
      title: "Pricing & Indexation",
      description: "Review pricing mechanism and indexation clauses.",
      required_expertise: ["financial-analysis", "contract-law"],
      complexity: "medium",
      created_at: nowIso,
    },
    {
      id: threadIds[1],
      contract_id: "dummy-contract",
      run_id: runId,
      title: "Termination & Penalties",
      description: "Review termination notice and penalty enforceability.",
      required_expertise: ["contract-law", "regulatory"],
      complexity: "high",
      created_at: nowIso,
    },
  ];

  const events: DummyEvent[] = [];
  let t = 400;
  let counter = 0;
  const proposalIds: string[] = [];

  function makeEntry(
    overrides: Partial<DraftEntry> &
      Pick<
        DraftEntry,
        | "author_id"
        | "author_name"
        | "entry_type"
        | "content"
        | "round"
        | "thread_id"
        | "documents_used"
      >,
  ): DraftEntry {
    counter += 1;
    return {
      id: makeId("dummy-entry", counter),
      run_id: runId,
      reply_to: null,
      mention_agents: [],
      is_visible: true,
      deleted_at: null,
      last_cited_round: 0,
      citation_count: 0,
      created_at: nowIso,
      children: [],
      ...overrides,
    };
  }

  // Round 1 — opening proposals, one per taker, alternating threads.
  takerAgents.forEach((agent, i) => {
    const entry = makeEntry({
      author_id: agent.id,
      author_name: agent.name,
      entry_type: "proposal",
      content: PROPOSALS[i % PROPOSALS.length],
      round: 1,
      thread_id: threadIds[i % threadIds.length],
      documents_used:
        i === 0
          ? ["master-services-agreement.pdf", "sla-appendix.pdf"]
          : undefined,
    });
    proposalIds.push(entry.id);
    events.push({ kind: "post", delay: t, entry });
    t += 700;
  });

  // Vote sub-round — each taker votes for the next taker's proposal.
  takerAgents.forEach((agent, i) => {
    const target = proposalIds[(i + 1) % proposalIds.length];
    const voteEntry = makeEntry({
      author_id: agent.id,
      author_name: agent.name,
      entry_type: "vote",
      content: "Strong, well-evidenced opening position.",
      round: 1,
      thread_id: threadIds[i % threadIds.length],
      reply_to: target,
    });
    events.push({ kind: "post", delay: t, entry: voteEntry });
    t += 500;
  });

  // Rounds 2..rounds — replies + citations.
  // Round 2: all agents reply directly to proposals.
  // Round 3+: every other agent (odd index) replies to a round-2 reply
  //           instead of the proposal, producing visible reply-to-reply nesting.
  const replyIdsByRound: Record<number, string[]> = {};

  for (let r = 2; r <= rounds; r += 1) {
    replyIdsByRound[r] = [];
    takerAgents.forEach((agent, i) => {
      const prevReplies = replyIdsByRound[r - 1] ?? [];
      const isReplyToReply = r >= 3 && i % 2 === 1 && prevReplies.length > 0;

      const targetId = isReplyToReply
        ? prevReplies[(i - 1) % prevReplies.length]
        : proposalIds[i % proposalIds.length];

      const mentionAgent =
        !isReplyToReply && i === 0 && takerAgents.length > 1
          ? takerAgents[1]
          : null;

      const content = isReplyToReply
        ? REPLIES_TO_REPLIES[(r + i) % REPLIES_TO_REPLIES.length]
        : REPLIES[(r + i) % REPLIES.length].replace(
            "{mention}",
            mentionAgent ? `@${mentionAgent.name} — ` : "",
          );

      const reply = makeEntry({
        author_id: agent.id,
        author_name: agent.name,
        entry_type: "reply",
        content,
        round: r,
        thread_id: threadIds[i % threadIds.length],
        reply_to: targetId,
        mention_agents: mentionAgent ? [mentionAgent.id] : [],
      });

      replyIdsByRound[r].push(reply.id);
      events.push({ kind: "post", delay: t, entry: reply });
      t += 650;

      events.push({
        kind: "cite",
        delay: t,
        entryId: proposalIds[0],
        citerName: agent.name,
        round: r,
      });
      t += 350;
    });
  }

  // Promote the first proposal once citations have accumulated.
  const promotionThreshold = Math.max(
    1,
    Math.floor(takerAgents.length / 3) + 1,
  );
  events.push({
    kind: "promote",
    delay: t,
    confirmed: {
      id: "dummy-confirmed-1",
      run_id: runId,
      thread_id: threadIds[0],
      source_draft_id: proposalIds[0],
      content: PROPOSALS[0],
      entry_type: "finding",
      citation_count: Math.max(promotionThreshold, takerAgents.length - 1),
      round_confirmed: rounds,
      created_at: nowIso,
    },
  });
  t += 900;

  // Soft-delete the least-cited proposal — stale after the decay window.
  if (proposalIds.length > 1) {
    events.push({
      kind: "delete",
      delay: t,
      entryId: proposalIds[proposalIds.length - 1],
    });
  }

  const domains = [
    "contract-law",
    "financial-analysis",
    "regulatory",
    "general",
  ];
  const trustVectors: DummyRunFixture["trustVectors"] = {};
  agents.forEach((a, i) => {
    trustVectors[a.id] = domains.map((domain, di) => ({
      domain,
      trust_score: Math.round((0.4 + ((i + di) % 4) * 0.13) * 100) / 100,
      runs_participated: 2 + ((i + di) % 4),
    }));
  });

  return { runId, threads, agents, events, trustVectors };
}
