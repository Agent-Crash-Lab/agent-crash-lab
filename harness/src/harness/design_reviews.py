"""Independently enforce both design gates before a plan can reach execution."""


def scenario_details(design, proposal, target):
    """Resolve normal use and exception references; old plans retain their original format."""
    field = design.get("morphology", {})
    usage = next(
        (
            c
            for c in field.get("candidates", [])
            if c["candidate_id"] == proposal.get("morphology_id")
        ),
        None,
    )
    if field.get("kind") != "NORMAL_USE_SCENARIOS":
        return usage, []
    if not usage or usage["tool_name"] != proposal["tool_name"] or usage["task"] != target["task"]:
        raise ValueError("정상 사용 시나리오의 업무·도구 연결이 올바르지 않습니다.")
    ids = proposal.get("exception_ids", [])
    catalog = {e["exception_id"]: e for e in field.get("exception_catalog", [])}
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= catalog.keys():
        raise ValueError("사용 시나리오에 적용할 예외 ID가 없거나 올바르지 않습니다.")
    exceptions = [catalog[eid] for eid in ids]
    permitted = {
        "AMBIGUOUS_WRITE": {"RESPONSE_LOSS"},
        "APPROVAL_BYPASS": {"APPROVAL_DENIED"},
        "RESOURCE_CONSTRAINT": {"MAINTENANCE", "OVERLAP", "PREDECESSOR_DELAY"},
        "UNVERIFIED_EVIDENCE": {"MISSING_RECORD", "FAILED_RECORD", "FAILED_CERTIFICATE"},
        "SUPPLIER_QUALIFICATION": {"UNQUALIFIED_SOURCE"},
    }.get(proposal["risk_key"], set())
    if any(
        e["risk_key"] != proposal["risk_key"]
        or proposal["tool_name"] not in e["tool_names"]
        or e["execution_support"] != "SUPPORTED"
        or e["condition"] not in permitted
        for e in exceptions
    ):
        raise ValueError("선택한 예외의 위험·도구 또는 실행 지원을 확인해야 합니다.")
    if len({e["phase"] for e in exceptions}) != 1:
        raise ValueError("현재 실행기는 여러 시점의 예외 조합을 지원하지 않습니다.")
    if any(e["phase"] not in {"INITIAL", "AFTER_APPROVAL_BEFORE_WRITE"} for e in exceptions):
        raise ValueError("등록되지 않은 예외 발생 시점입니다.")
    return usage, exceptions


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
            if stage.get("scores") is not None or stage.get("score_total") is not None:
                raise ValueError("A skipped gate must not receive an invented score")
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
        scores = stage.get("scores", {})
        score_keys = {"domain_fit_score", "causal_path_score", "constraint_score", "evidence_score"}
        if set(scores) != score_keys or any(
            type(value) is not int or value not in (0, 1, 2) for value in scores.values()
        ):
            raise ValueError("Review rubric scores are incomplete or outside 0..2")
        score_total = sum(scores.values())
        if stage.get("score_total") != score_total or stage.get("score_max") != 8:
            raise ValueError("Review score total does not match its criteria")
        explanations = stage.get("score_reasons", {})
        quote_gated = stage.get("method") != "TWO_STAGE_SEMANTIC_V1"
        explanation_keys = score_keys | ({"evidence_quote"} if quote_gated else set())
        if (
            set(explanations) != explanation_keys
            or any(
                not isinstance(explanations.get(key), str) or not explanations[key].strip()
                for key in score_keys
            )
            or (quote_gated and not isinstance(explanations.get("evidence_quote"), str))
        ):
            raise ValueError("Each review score needs its own explanation")
        if quote_gated:
            quote = explanations["evidence_quote"]
            quote_verified = any(
                quote and quote in sources.get(sid, {}).get("matched_text", "")
                for sid in stage.get("evidence_ids", [])
            )
            if not quote_verified and (
                stage["assessment"]["evidence_relevance"] != "UNCLEAR"
                or scores["evidence_score"] != 0
            ):
                raise ValueError("Unsupported domain claims cannot pass the review gate")
        expected = (
            "REJECT"
            if values & {"CONFLICT", "IRRELEVANT", "CONTRADICTORY"}
            else "NEEDS_INFORMATION"
            if "UNCLEAR" in values or score_total < 6 or min(scores.values()) < 1
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
