"""Investigation report checks done independently of the Agent (HARNESS_SPEC 2.6, 2.7)."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ALLOWED_INVESTIGATION_TOOLS = {
    "get_failed_checks",
    "get_run_trace",
    "get_business_state",
    "search_failure_guides",
    "read_resource",
}
EVIDENCE_KEYS = {"evidence_id", "evidence_ids", "snapshot_evidence_ids", "commit_evidence_ids"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Fact(_Model):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class _Source(_Model):
    document_id: str
    version: str
    location: str


class _Improvement(_Model):
    text: str = Field(min_length=1)
    sources: list[_Source] = Field(min_length=1)


class InvestigationReport(_Model):
    target_run_id: str
    facts: list[_Fact]
    cause_candidates: list[str]
    missing_evidence: list[str]
    improvements: list[_Improvement]
    retest_scenario_ids: list[Literal["S01", "S02", "S03"]]


def collect_evidence_ids(value) -> set[str]:
    """Evidence IDs anywhere in events, checks, observations or fixture evidence."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in EVIDENCE_KEYS:
                if isinstance(item, str):
                    found.add(item)
                elif isinstance(item, list):
                    found.update(x for x in item if isinstance(x, str))
            else:
                found.update(collect_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(collect_evidence_ids(item))
    return found


def validate_report(
    report: dict | None,
    target_run_id: str,
    known_evidence: set[str],
    agent_events: list[dict],
    runs_citing: Callable[[str], set[str]],
) -> dict:
    errors: list[dict] = []
    try:
        parsed = InvestigationReport.model_validate(report)
        if parsed.target_run_id != target_run_id:
            errors.append({"type": "SCHEMA_INVALID", "value": "target_run_id"})
        cited = {eid for fact in parsed.facts for eid in fact.evidence_ids}
    except ValidationError as exc:
        errors.append({"type": "SCHEMA_INVALID", "value": str(exc.errors()[0]["loc"])})
        cited = collect_evidence_ids(report or {})

    for evidence_id in sorted(cited - known_evidence):
        others = runs_citing(evidence_id) - {target_run_id}
        kind = "FOREIGN_RUN_EVIDENCE" if others else "UNKNOWN_EVIDENCE"
        errors.append({"type": kind, "value": evidence_id})

    for event in agent_events:
        if event["event_type"] == "AGENT_TOOL_CALLED":
            tool = event["payload"].get("tool")
            if tool not in ALLOWED_INVESTIGATION_TOOLS:
                errors.append({"type": "DISALLOWED_TOOL", "value": str(tool)})

    return {"passed": not errors, "errors": errors}
