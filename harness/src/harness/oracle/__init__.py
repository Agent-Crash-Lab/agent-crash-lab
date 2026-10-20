"""Oracle boundary for SYSTEM tests (HARNESS_SPEC §6). Owner: 문관영.

Reads the business DB itself through ORACLE_DATABASE_URL (oracle_ro), then applies the
catalog rules (rules.py). The MCP finalize response and the Agent's report are not the
source of truth: the Agent's report is checked against the DB like any other claim.
"""

from dataclasses import dataclass

from harness.oracle.observe import observe
from harness.oracle.rules import judge


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
    return judge(ctx, observe(ctx.oracle_database_url, ctx.run_id, ctx.request_id))
