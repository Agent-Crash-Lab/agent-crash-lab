"""Independently enforce both design gates before a plan can reach execution."""


def validate_staged_review(review, proposal, sources, records):
    if review.get("method") == "CODE_PREREQUISITES":
        if review["decision"] == "ACCEPT_FOR_BINDING":
            raise ValueError("Prerequisites cannot replace two review gates")
        return
    stages = review.get("stages", [])
    if [s.get("stage") for s in stages] != ["MANUFACTURING", "AGENTIC"]:
        raise ValueError("Both ordered review gates are required")
    for stage in stages:
        if stage.get("status") == "SKIPPED":
            if stage["stage"] != "AGENTIC" or stages[0]["decision"] == "ACCEPT_FOR_BINDING":
                raise ValueError("A required review gate was skipped")
            if stage["decision"] != "NEEDS_INFORMATION":
                raise ValueError("A skipped gate cannot accept a proposal")
            continue
        if stage.get("status") != "COMPLETED" or not stage.get("evidence_ids"):
            raise ValueError("A completed review needs its own citations")
        for sid in stage["evidence_ids"]:
            hit = sources.get(sid, {})
            record = records.get(hit.get("source_id"), {})
            if (
                sid not in proposal["evidence_ids"]
                or stage["stage"] not in record.get("evidence_domains", [])
                or hit.get("version") != record.get("sha256")
                or proposal["risk_key"] not in record.get("risk_types", [])
            ):
                raise ValueError("Review citation is outside its domain, version or risk")
        values = set(stage.get("assessment", {}).values())
        if set(stage.get("assessment", {})) != {
            "policy_alignment",
            "evidence_relevance",
            "scenario_consistency",
        }:
            raise ValueError("Review criteria are incomplete")
        expected = (
            "REJECT"
            if values & {"CONFLICT", "IRRELEVANT", "CONTRADICTORY"}
            else "NEEDS_INFORMATION"
            if "UNCLEAR" in values
            else "ACCEPT_FOR_BINDING"
        )
        if stage["decision"] != expected:
            raise ValueError("Review decision contradicts its criteria")
    decisions = {s["decision"] for s in stages}
    expected = (
        "REJECT"
        if "REJECT" in decisions
        else "NEEDS_INFORMATION"
        if "NEEDS_INFORMATION" in decisions
        else "ACCEPT_FOR_BINDING"
    )
    if review["decision"] != expected:
        raise ValueError("Overall review must respect both gates")
