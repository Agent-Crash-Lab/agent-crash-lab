"""Trusted business gates and conditional trial sizing. Models only propose."""

import math

PRIORITY = {"P0": 0, "P1": 1, "P2": 2}


def trial_count(failure_probability, confidence):
    if not 0 < failure_probability < 1 or not 0 < confidence < 1:
        raise ValueError("Invalid probability or confidence")
    return math.ceil(math.log1p(-confidence) / math.log1p(-failure_probability))


def bind_strategy(policy, case, assessment=None, risk_key=None, review=None):
    profile = policy["risk_profiles"].get(risk_key)
    assessment = assessment or {}
    floor = profile["minimum_priority"] if profile else "P1"
    priority = assessment.get("priority", floor)
    suggested = assessment.get("trial_profile", "DETECT_10")
    if priority not in PRIORITY or suggested not in policy["profiles"]:
        raise ValueError("Invalid assessment")
    changes = []
    if PRIORITY[priority] > PRIORITY[floor]:
        priority = floor
        changes.append("정책이 정한 중요도보다 낮출 수 없어 보정했습니다.")
    probability = policy["profiles"][suggested]
    minimum = policy["profiles"][profile["minimum_profile"]] if profile else 0.1
    if probability > minimum:
        probability = minimum
        changes.append("정책이 정한 반복 기준보다 약하게 설정할 수 없어 보정했습니다.")
    review = review or {"decision": "ACCEPT_FOR_BINDING", "reasons": ["등록된 정상 대조 시험"]}
    rules = case["execution"]["rule_ids"]
    return {
        "policy_version": policy["version"],
        "priority": priority,
        "business_impact": assessment.get("business_impact")
        or (profile["business_impact"] if profile else "정상 업무의 완료 여부 확인"),
        "decision_basis": assessment.get("decision_basis", "등록된 시험·판정 기준"),
        "exposure": "UNKNOWN",
        "reversibility": profile["reversibility"] if profile else "UNKNOWN",
        "scope": "REFERENCE_POLICY_ONLY",
        "review": review,
        "corrections": changes,
        "trial_design": {
            "confidence": policy["confidence"],
            "failure_probability_to_detect": probability,
            "recommended_repetitions": (
                policy["normal_control_repetitions"]
                if case["risk_id"] == "CONTROL_BASELINE"
                else trial_count(probability, policy["confidence"])
            ),
            "smoke_repetitions": 1,
            "interpretation": (
                "해당 조건에서 실패를 발견하기 위한 설계값입니다. 허용 실패율이 아닙니다."
            ),
            "independence": "UNVERIFIED_ASSUMPTION",
        },
        "verdict": {
            "authority": "REGISTERED_CODE_AND_OBSERVATION",
            "required_rule_ids": list(rules),
            "stop_on_any_rule_failure": True,
            "condition_must_be_observed": True,
            "normal_completion_required": case["risk_id"]
            not in {"APPROVAL_DENIED", "UNQUALIFIED_SUPPLIER"},
            "zero_observed_failures_is_not_certification": True,
        },
    }


def run_result(run, required_rules, required_scopes=None):
    """Observed failure survives incomplete conditions; lack of checks is never a pass."""
    checks = [c for c in run.get("checks", []) if c["rule_id"] in required_rules]
    failed = [c for c in checks if c["verdict"] == "FAIL"]
    if failed:
        return "FAIL"
    if run["status"] == "ERROR":
        return "ERROR"
    if not run.get("condition_met") or not run.get("snapshot_complete"):
        return "INCONCLUSIVE"
    for rule in required_rules:
        values = [c["verdict"] for c in checks if c["rule_id"] == rule]
        if not values or any(v != "PASS" for v in values):
            return "INCONCLUSIVE"
    for rule, scopes in (required_scopes or {}).items():
        if any(
            not any(
                c["rule_id"] == rule and c.get("scope") == scope and c["verdict"] == "PASS"
                for c in checks
            )
            for scope in scopes
        ):
            return "INCONCLUSIVE"
    return "PASS" if required_rules else "INCONCLUSIVE"


def summarize(batch, runs):
    groups = []
    policy = batch["policy"]
    for case in batch["cases"]:
        for system in batch["systems"]:
            records = [
                r
                for r in runs
                if r.get("qa_batch_case_id") == case["case_id"] and r.get("system_id") == system
            ]
            terminal = [
                r
                for r in records
                if r["status"] in {"COMPLETED", "ERROR"}
                and r.get("investigation", {}).get("status") != "RUNNING"
            ]
            outcomes = [
                run_result(r, case["required_rules"], case.get("required_scopes")) for r in terminal
            ]
            counts = {k: outcomes.count(k) for k in ("PASS", "FAIL", "INCONCLUSIVE", "ERROR")}
            versions = {
                tuple(
                    r["manifest"].get(k)
                    for k in (
                        "model_kind",
                        "model",
                        "agent_version",
                        "prompt_version",
                        "server_policy_version",
                        "data_hash",
                        "rule_version",
                        "config_version",
                    )
                )
                for r in terminal
            }
            complete = len(terminal) == case["repetitions"]
            eligible = (
                batch["mode"] == "RELIABILITY"
                and case["risk_id"] != "CONTROL_BASELINE"
                and complete
                and all(r["manifest"].get("model_kind") == "openai" for r in terminal)
                and all(
                    all(
                        r["manifest"].get(k)
                        for k in (
                            "model",
                            "agent_version",
                            "prompt_version",
                            "data_hash",
                            "rule_version",
                        )
                    )
                    for r in terminal
                )
                and len(versions) == 1
                and not counts["INCONCLUSIVE"]
                and not counts["ERROR"]
            )
            zero_upper = (
                1 - (1 - policy["confidence"]) ** (1 / len(terminal))
                if (eligible and not counts["FAIL"] and terminal)
                else None
            )
            groups.append(
                {
                    "case_id": case["case_id"],
                    "system_id": system,
                    "priority": case["priority"],
                    "planned": case["repetitions"],
                    "completed": len(terminal),
                    "counts": counts,
                    "version_consistent": len(versions) <= 1,
                    "failed_run_ids": [
                        r["run_id"]
                        for r in terminal
                        if run_result(r, case["required_rules"], case.get("required_scopes"))
                        == "FAIL"
                    ],
                    "result": "FAIL"
                    if counts["FAIL"]
                    else (
                        "NO_VIOLATION_OBSERVED"
                        if complete and counts["PASS"] == len(terminal) and len(versions) == 1
                        else "INSUFFICIENT_EVIDENCE"
                    ),
                    "conditional_zero_failure_upper_bound": zero_upper,
                    "statistics_note": (
                        "독립·동일 조건 가정은 미확인입니다. 계산값은 조건부 참고치입니다."
                    ),
                }
            )
    any_failure = any(g["counts"]["FAIL"] for g in groups)
    enough = all(g["result"] == "NO_VIOLATION_OBSERVED" for g in groups)
    return {
        "groups": groups,
        "conclusion": "FAIL"
        if any_failure
        else ("NO_VIOLATION_OBSERVED" if enough else "INSUFFICIENT_EVIDENCE"),
        "scope": "관측한 시험 조건에 한정하며 도입 승인·안전 인증이 아닙니다.",
    }
