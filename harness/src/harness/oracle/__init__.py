"""Oracle boundary for SYSTEM tests (HARNESS_SPEC §6). Owner: 문관영.

Placeholder: returns no checks until the Oracle reads the business DB through
ORACLE_DATABASE_URL (oracle_ro) and applies the catalog rules.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OracleContext:
    run_id: str
    test_id: str
    request_id: str
    rule_ids: list[str]  # catalog.json oracle_rule_ids
    rule_version: str  # config evaluation.rule_version
    rule_scopes: dict[str, list[str]]  # config evaluation.rule_check_scopes
    snapshot_complete: bool  # MCP_SPEC 3.4
    faults: list[dict]  # MCP_SPEC 3.3 faults
    agent_result: dict | None  # the Agent's claim; one input among others
    agent_termination: str | None
    oracle_database_url: str


def evaluate(ctx: OracleContext) -> list[dict]:
    """Return QaCheck dicts (qa-check.schema.json). Raise on environment errors."""
    return []
