"""The per-round prompts must ask for concise markdown, deltas, and stand-down."""

from __future__ import annotations

from server.market_hive.prompts import (
    round_one_system_suffix,
    rounds_system_suffix,
)


def test_round_one_asks_for_concise_markdown() -> None:
    suffix = round_one_system_suffix("Be measured.")
    lower = suffix.lower()
    assert "markdown" in lower
    # A brevity signal must be present.
    assert "concise" in lower or "brief" in lower or "short" in lower


def test_discussion_rounds_advertise_stand_down_and_delta() -> None:
    suffix = rounds_system_suffix("Be measured.")
    lower = suffix.lower()
    assert "stand_down" in lower
    # Delta discipline: do not restate.
    assert "restate" in lower or "delta" in lower or "repeat" in lower
    assert "markdown" in lower


def test_discussion_rounds_do_not_demand_a_qualification_line() -> None:
    suffix = rounds_system_suffix("Be measured.")
    # The verbose "why you are qualified" preamble belongs to round 1 only.
    assert "qualified" not in suffix.lower()
