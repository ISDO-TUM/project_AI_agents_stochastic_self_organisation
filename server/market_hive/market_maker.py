"""Market Maker — prompt → Contract + Threads, and amendment voting (PRD §6.1).

Not yet implemented — intentionally skipped for now. The orchestrator runs on the
no-LLM ``FallbackContractSource`` in ``server/market_hive/contract_source.py``
until the real Market Maker lands. When built, ``MarketMaker.make_contract`` will
implement the same ``ContractSource`` protocol (see ``orchestrator.py``) and drop
in with no change to the run loop.
"""
