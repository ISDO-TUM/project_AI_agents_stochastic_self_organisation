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
