"""Oracle boundary for SYSTEM tests (HARNESS_SPEC §6). Owner: 문관영.

Reads the business DB itself through ORACLE_DATABASE_URL (oracle_ro), then applies the
catalog rules (rules.py). The MCP finalize response and the Agent's report are not the
source of truth: the Agent's report is checked against the DB like any other claim.
"""

from dataclasses import dataclass, field

from harness.adapters.reference_purchase.observe import observe
from harness.adapters.reference_purchase.rules import judge


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
    expected_faults: list[dict] = field(default_factory=list)
    adapter_id: str = "reference-purchase-v1"


def evaluate(ctx: OracleContext) -> list[dict]:
    """Return QaCheck dicts (qa-check.schema.json). Raise on environment errors."""
    if ctx.adapter_id != "reference-purchase-v1":
        raise ValueError("No registered code evaluator for this target")
    return judge(ctx, observe(ctx.oracle_database_url, ctx.run_id, ctx.request_id))
