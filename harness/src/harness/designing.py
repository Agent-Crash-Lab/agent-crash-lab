"""One bounded repair of withheld drafts. Never execute business tools here."""

import copy

from jsonschema.exceptions import SchemaError, ValidationError

from harness.clients import ClientError

REPAIRABLE = {"generated_data_validation", "design_prerequisites", "design_review"}


async def design_with_repair(agents, planner, data):
    original = await agents.design(data)
    plan = planner.build_designed(data["target"], data["sample_data"], original)
    if original.get("version") != "4.0.0":
        return original
    feedback = []
    for case in plan["cases"]:
        basis, execution = case.get("design_basis", {}), case["execution"]
        missing = set(execution["missing_capabilities"])
        if basis and execution["status"] != "READY" and missing and missing <= REPAIRABLE:
            review = case.get("evaluation_strategy", {}).get("review", {})
            feedback.append(
                {
                    "proposal_id": basis["proposal_id"],
                    "reasons": [execution["reason"], *review.get("reasons", [])][:6],
                }
            )
    audit = {"max_attempts": 1, "attempts": 0, "status": "NOT_NEEDED", "feedback": feedback}
    if not feedback:
        return {**original, "repair": audit}
    audit.update(
        attempts=1,
        status="NOT_REPAIRED",
        original_proposals=original["proposals"],
        original_reviews=original["reviews"],
    )
    audit["original_model_metadata"] = {
        key: original.get(key)
        for key in (
            "generation_model",
            "review_model",
            "generation_prompt_version",
            "generation_schema_version",
            "review_prompt_version",
        )
    }
    ids = {f["proposal_id"] for f in feedback}
    request = {
        **data,
        "repair": {
            "previous_proposals": original["proposals"],
            "feedback": feedback,
            "index_version": original["retrieval"][0]["index_version"],
        },
    }
    try:
        updated = await agents.design(request)
        before = {p["proposal_id"]: p for p in original["proposals"]}
        after = {p["proposal_id"]: p for p in updated["proposals"]}
        if before.keys() != after.keys() or len(after) != len(updated["proposals"]):
            raise ValueError("Repair changed proposal identities")
        for pid, proposal in before.items():
            if pid not in ids and proposal != after[pid]:
                raise ValueError("Repair changed an accepted proposal")
            if any(proposal[k] != after[pid][k] for k in ("risk_key", "tool_name", "risk_type")):
                raise ValueError("Repair changed risk or tool")
        old_reviews = {row["proposal_id"]: row for row in original["reviews"]}
        updated["reviews"] = [
            row if row["proposal_id"] in ids else old_reviews[row["proposal_id"]]
            for row in updated["reviews"]
        ]
        candidate = planner.build_designed(data["target"], data["sample_data"], updated)
        repaired = sum(
            c["execution"]["status"] == "READY"
            for c in candidate["cases"]
            if c.get("design_basis", {}).get("proposal_id") in ids
        )
        audit["status"] = (
            "REPAIRED"
            if repaired == len(ids)
            else "PARTIALLY_REPAIRED"
            if repaired
            else "NOT_REPAIRED"
        )
        audit["remaining"] = [
            {"proposal_id": c["design_basis"]["proposal_id"], "reason": c["execution"]["reason"]}
            for c in candidate["cases"]
            if c.get("design_basis", {}).get("proposal_id") in ids
            and c["execution"]["status"] != "READY"
        ]
        usage = original.get("llm_usage", {})
        updated["llm_usage"] = {
            k: usage.get(k, 0) + updated.get("llm_usage", {}).get(k, 0)
            for k in usage.keys() | updated.get("llm_usage", {}).keys()
        }
        return {**updated, "repair": audit}
    except ClientError as exc:
        audit["status"] = (
            "BUDGET_EXHAUSTED" if exc.code == "LLM_BUDGET_EXHAUSTED" else "REPAIR_UNAVAILABLE"
        )
    except (ValueError, KeyError, TypeError, SchemaError, ValidationError):
        audit["status"] = "INVALID_REPAIR"
    return {**copy.deepcopy(original), "repair": audit}
