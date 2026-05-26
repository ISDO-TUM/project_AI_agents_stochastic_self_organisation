from httpx import AsyncClient
from sqlalchemy import insert

from server.db import create_connection, create_round, create_trial, get_engine
from server.db.tables import agents
from server.routes.history import _VALID_MESSAGE_TYPES
from server.routes.simulation import _simulation_trial_description
from server.simulation import _extract_reason, _extract_vote, _tally


def test_tally_ignores_unknown_votes() -> None:
    plurality, counts = _tally(
        {
            "agent_1": "unknown",
            "agent_2": "acme computers",
            "agent_3": "unknown",
        }
    )

    assert plurality == "acme computers"
    assert counts == {"acme computers": 1}


def test_tally_returns_no_plurality_when_only_unknown_votes() -> None:
    plurality, counts = _tally({"agent_1": "unknown", "agent_2": None})

    assert plurality is None
    assert counts == {}


def test_unknown_vote_is_normalized_before_tallying() -> None:
    vote = _extract_vote("I cannot find it.\nVOTE: Unknown!")

    assert vote == "unknown"
    assert _tally({"agent_1": vote}) == (None, {})


def test_extract_vote_accepts_markdown_list_formatting() -> None:
    vote = _extract_vote("I found the access code.\n- **VOTE:** `Z`")

    assert vote == "z"


def test_extract_vote_accepts_hyphen_separator() -> None:
    vote = _extract_vote("REASON - The file states the answer.\nVOTE - Dylan")

    assert vote == "dylan"


def test_tally_counts_markdown_formatted_votes() -> None:
    votes = {
        "agent_1": _extract_vote("VOTE: Z"),
        "agent_2": _extract_vote("- **VOTE:** Z"),
        "agent_3": _extract_vote("1. **Vote** - `Z`"),
    }

    assert _tally(votes) == ("z", {"z": 3})


def test_extract_reason_returns_last_reason_line() -> None:
    reason = _extract_reason(
        "REASON: preliminary note\n"
        "Some explanation.\n"
        "REASON: Acme Computers was chosen due to the quote 'approved supplier' "
        "from 2026_supplier_contract.txt\n"
        "VOTE: Acme Computers"
    )

    assert (
        reason == "Acme Computers was chosen due to the quote 'approved supplier' "
        "from 2026_supplier_contract.txt"
    )


def test_extract_reason_accepts_markdown_list_formatting() -> None:
    reason = _extract_reason("- **REASON:** The file says code Z belongs to Dylan.")

    assert reason == "The file says code Z belongs to Dylan."


def test_simulation_trial_description_includes_timestamp() -> None:
    description = _simulation_trial_description("plurality_voting")

    assert description.startswith("plurality_voting run - ")
    assert "T" in description
    assert description.endswith("+00:00")


async def test_create_connection_reuses_system_connection(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        await conn.execute(
            insert(agents).values(
                id="agent_a",
                name="Agent A",
                description="A test agent.",
                system_prompt="Answer briefly.",
                provider="openai",
                model="gpt-4o",
                tools="[]",
                connections="[]",
            )
        )
        await conn.commit()

        trial_id = await create_trial(conn, "Prompt", "Test trial", "broadcast_no_consensus")
        round_id = await create_round(conn, trial_id, 1, "broadcast")

        first_id = await create_connection(conn, round_id, None, "agent_a")
        second_id = await create_connection(conn, round_id, None, "agent_a")

    assert second_id == first_id


async def test_history_accepts_simulation_message_type_filters(client: AsyncClient) -> None:
    expected_types = {
        "agent_error",
        "agent_output",
        "agent_to_agent",
        "system_broadcast",
        "tool",
        "trust_update",
        "vote_tally",
        "voting_agent_to_agent",
        "voting_tally",
        "weighted_agent_to_agent",
    }

    assert expected_types <= _VALID_MESSAGE_TYPES

    for message_type in expected_types:
        response = await client.get(f"/api/history/messages?message_type={message_type}")
        assert response.status_code == 200
