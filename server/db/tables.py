"""SQLAlchemy Core table definitions shared by every dialect.

Defining the schema with Core constructs (rather than raw ``CREATE TABLE``
strings) lets the same code emit SQLite DDL for the test suite and PostgreSQL
DDL in production. JSON-bearing columns (``tools``, ``connections``) stay as
TEXT so the application keeps owning (de)serialisation via :mod:`json`.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
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
)

rounds = Table(
    "rounds",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trial_id", Text, ForeignKey("trials.id"), nullable=False),
)

connections = Table(
    "connections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("round_id", Integer, ForeignKey("rounds.id"), nullable=False),
    Column("from_agent_id", Text, ForeignKey("agents.id"), nullable=False),
    Column("to_agent_id", Text, ForeignKey("agents.id"), nullable=False),
    UniqueConstraint("round_id", "from_agent_id", "to_agent_id", name="uq_connections_edge"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("connection_id", Integer, ForeignKey("connections.id"), nullable=False),
    Column("message", Text),
)
