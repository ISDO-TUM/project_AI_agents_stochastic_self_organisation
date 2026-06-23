"""SQLAlchemy Core table definitions shared by every dialect.

Defining the schema with Core constructs (rather than raw ``CREATE TABLE``
strings) lets the same code emit SQLite DDL for the test suite and PostgreSQL
DDL in production. JSON-bearing columns (``tools``, ``connections``) stay as
TEXT so the application keeps owning (de)serialisation via :mod:`json`.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

metadata = MetaData()

agents = Table(
    "agents",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("system_prompt", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("tools", Text, nullable=False, server_default=text("'[]'")),
    Column("connections", Text, nullable=False, server_default=text("'[]'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # JSON-encoded float vector describing the agent's expertise. Used by the
    # ECSAS auction engine to score agents against a contract embedding. TEXT so
    # the application owns (de)serialisation, NULL until an embedding is computed.
    Column("capability_embedding", Text),
    CheckConstraint(
        "provider IN ('openai', 'anthropic', 'groq', 'gemini')",
        name="ck_agents_provider",
    ),
)

knowledge_files = Table(
    "knowledge_files",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

agent_files = Table(
    "agent_files",
    metadata,
    Column("agent_id", Text, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "file_id",
        Text,
        ForeignKey("knowledge_files.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

trials = Table(
    "trials",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_prompt", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("mode", Text),
    Column("status", Text, nullable=False, server_default=text("'running'")),
    Column("created_at", Text, nullable=False),
    Column("completed_at", Text),
)

rounds = Table(
    "rounds",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trial_id", Text, ForeignKey("trials.id", ondelete="CASCADE"), nullable=False),
    Column("round_index", Integer, nullable=False),
    Column("phase", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("trial_id", "round_index", "phase", name="uq_rounds_trial_round_phase"),
)

# NOTE: ``from_agent_id``/``to_agent_id`` deliberately carry NO foreign key to
# ``agents``. The run history is an immutable event log: clearing the canvas
# deletes the agents, but the history that powers the statistics views must
# survive. A CASCADE would delete these rows and a SET NULL would erase the
# agent identity the per-agent stats aggregate on — so the columns are plain
# denormalised snapshots of the agent id, paired with ``from_agent_name``/
# ``to_agent_name`` snapshots taken at write time so the history stays both
# attributable and human-readable after the referenced agents are gone.
connections = Table(
    "connections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("round_id", Integer, ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False),
    Column("from_agent_id", Text, nullable=True),
    Column("to_agent_id", Text, nullable=True),
    Column("from_agent_name", Text),
    Column("to_agent_name", Text),
    UniqueConstraint("round_id", "from_agent_id", "to_agent_id", name="uq_connections_edge"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "connection_id", Integer, ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    ),
    Column("round_id", Integer, ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False),
    Column("from_agent_id", Text, nullable=True),
    Column("to_agent_id", Text, nullable=True),
    Column("from_agent_name", Text),
    Column("to_agent_name", Text),
    Column("message_type", Text, nullable=False),
    Column("message", Text),
    Column("created_at", Text, nullable=False),
)

# ── ECSAS swarm tables ────────────────────────────────────────────────────────

swarm_runs = Table(
    "swarm_runs",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "status",
        Text,
        nullable=False,
        server_default=text("'running'"),
    ),
    Column("mode", Text, nullable=False, server_default=text("'swarm'")),
    Column("termination_reason", Text),
    Column("termination_round", Integer),
    Column("amendment_count", Integer, nullable=False, server_default=text("0")),
    Column("token_usage", Text, nullable=False, server_default=text("'{}'")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("completed_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('running','completed','failed','aborted')",
        name="ck_swarm_runs_status",
    ),
    CheckConstraint("mode IN ('swarm','topology')", name="ck_swarm_runs_mode"),
)

contracts = Table(
    "contracts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("original_prompt", Text, nullable=False),
    Column("task_type", Text, nullable=False),
    Column("task_nature", Text, nullable=False, server_default=text("'single'")),
    Column("required_expertise", Text, nullable=False, server_default=text("'[]'")),
    Column("complexity", Text, nullable=False, server_default=text("'medium'")),
    Column("confidence", Float, nullable=False, server_default=text("0.0")),
    Column("contract_embedding", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("task_nature IN ('single','multi')", name="ck_contracts_task_nature"),
    CheckConstraint("complexity IN ('low','medium','high')", name="ck_contracts_complexity"),
)

threads = Table(
    "threads",
    metadata,
    Column("id", Text, primary_key=True),
    Column("contract_id", Text, ForeignKey("contracts.id"), nullable=False),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("required_expertise", Text, nullable=False, server_default=text("'[]'")),
    Column("complexity", Text, nullable=False, server_default=text("'medium'")),
    Column("thread_embedding", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

draft_entries = Table(
    "draft_entries",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("thread_id", Text, ForeignKey("threads.id"), nullable=False),
    Column("round", Integer, nullable=False),
    Column("author_id", Text, ForeignKey("agents.id"), nullable=False),
    Column(
        "entry_type",
        Text,
        nullable=False,
    ),
    Column("content", Text, nullable=False),
    Column("content_embedding", Text),
    Column("reply_to", Text, ForeignKey("draft_entries.id")),
    Column("mention_agents", Text, nullable=False, server_default=text("'[]'")),
    Column("is_visible", Boolean, nullable=False, server_default=text("true")),
    Column("deleted_at", DateTime(timezone=True)),
    Column("last_cited_round", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "entry_type IN ('proposal','reply','vote','system')",
        name="ck_draft_entries_type",
    ),
)

citations = Table(
    "citations",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("citing_agent_id", Text, ForeignKey("agents.id"), nullable=False),
    Column("cited_entry_id", Text, ForeignKey("draft_entries.id"), nullable=False),
    Column("citing_entry_id", Text, ForeignKey("draft_entries.id")),
    Column("round", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("citing_agent_id", "cited_entry_id", "round", name="uq_citations_per_round"),
)

votes = Table(
    "votes",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("voter_agent_id", Text, ForeignKey("agents.id"), nullable=False),
    Column("voted_entry_id", Text, ForeignKey("draft_entries.id"), nullable=False),
    Column("thread_id", Text, ForeignKey("threads.id"), nullable=False),
    Column("round", Integer, nullable=False, server_default=text("1")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("voter_agent_id", "voted_entry_id", name="uq_votes_per_entry"),
)

confirmed_entries = Table(
    "confirmed_entries",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("thread_id", Text, ForeignKey("threads.id"), nullable=False),
    Column("source_draft_id", Text, ForeignKey("draft_entries.id")),
    Column("content", Text, nullable=False),
    Column("content_embedding", Text),
    Column(
        "entry_type",
        Text,
        nullable=False,
        server_default=text("'finding'"),
    ),
    Column("citation_count", Integer, nullable=False, server_default=text("0")),
    Column("round_confirmed", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "entry_type IN ('anchor','finding','system')",
        name="ck_confirmed_entries_type",
    ),
)

# ── Bids (auction self-selection) ─────────────────────────────────────────────
# One row per agent's decision in the auction: a submitted bid, an abstention, or
# the outcome of taker selection. ``contract_id``/``thread_id`` are nullable so a
# row can scope to the whole contract (single-step) or a specific thread.
bids = Table(
    "bids",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("contract_id", Text, ForeignKey("contracts.id")),
    Column("thread_id", Text, ForeignKey("threads.id")),
    Column("agent_id", Text, ForeignKey("agents.id"), nullable=False),
    Column("justification", Text, nullable=False, server_default=text("''")),
    Column("preliminary_score", Float, nullable=False, server_default=text("0.0")),
    Column("is_taker", Boolean, nullable=False, server_default=text("false")),
    Column("is_observer", Boolean, nullable=False, server_default=text("false")),
    Column("abstained", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# ── Per-run reputation ────────────────────────────────────────────────────────
# An agent's domain credibility *within a single run*. Starts at 0.5 and is reset
# between runs (hence the run_id in the composite key); feeds conceding
# temperature in the convergence engine.
reputation = Table(
    "reputation",
    metadata,
    Column("run_id", Text, ForeignKey("swarm_runs.id"), primary_key=True, nullable=False),
    Column("agent_id", Text, ForeignKey("agents.id"), primary_key=True, nullable=False),
    Column("domain", Text, primary_key=True, nullable=False),
    Column("score", Float, nullable=False, server_default=text("0.5")),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_reputation_score"),
)

# ── Cross-run trust (persistent) ──────────────────────────────────────────────
# Per-agent, per-domain credibility that *persists across runs*. Updated at run
# end (winner gain / observer loss) and fed back into bid scoring. Starts at 0.5.
agent_trust = Table(
    "agent_trust",
    metadata,
    Column("agent_id", Text, ForeignKey("agents.id"), primary_key=True, nullable=False),
    Column("domain", Text, primary_key=True, nullable=False),
    Column("trust_score", Float, nullable=False, server_default=text("0.5")),
    Column("runs_participated", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("trust_score >= 0.0 AND trust_score <= 1.0", name="ck_agent_trust_score"),
)

# ── Amendment proposals ───────────────────────────────────────────────────────
# A taker's ``request_expertise`` proposal to widen the contract scope. Resolved
# by a majority vote of existing takers + the Market Maker.
amendments = Table(
    "amendments",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("swarm_runs.id"), nullable=False),
    Column("proposing_agent_id", Text, ForeignKey("agents.id"), nullable=False),
    Column("thread_id", Text, ForeignKey("threads.id")),
    Column("requested_domain", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("approve_votes", Integer, nullable=False, server_default=text("0")),
    Column("total_voters", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "status IN ('pending','approved','rejected')",
        name="ck_amendments_status",
    ),
)

# ── Indexes (PRD §7.1) ────────────────────────────────────────────────────────
# Attention queries, citation counting and confirmed-layer reads run on every
# round, so the hot lookup paths are indexed explicitly.
Index(
    "idx_draft_run_thread_round",
    draft_entries.c.run_id,
    draft_entries.c.thread_id,
    draft_entries.c.round,
)
Index("idx_draft_visible", draft_entries.c.run_id, draft_entries.c.is_visible)
Index("idx_draft_reply_to", draft_entries.c.reply_to)
Index("idx_citations_cited", citations.c.cited_entry_id, citations.c.run_id)
Index("idx_citations_agent", citations.c.citing_agent_id, citations.c.run_id)
Index("idx_confirmed_run_thread", confirmed_entries.c.run_id, confirmed_entries.c.thread_id)
Index("idx_confirmed_citations", confirmed_entries.c.citation_count.desc())
Index("idx_bids_run", bids.c.run_id, bids.c.is_taker)
Index("idx_trust_agent_domain", agent_trust.c.agent_id, agent_trust.c.domain)
