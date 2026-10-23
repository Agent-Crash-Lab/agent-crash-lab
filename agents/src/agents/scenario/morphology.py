"""Target-bound factors, normal-use candidates, and executable exception options.

These are project mappings, not frequencies or a certified manufacturing taxonomy.
The model supplies concrete values; the Harness still proves execution support.
"""

from agents.scenario.exceptions import build_catalog, check_exceptions

METHOD = {
    "version": "3.0.0",
    "reference": "https://www.swemorph.com/ma.html",
    "scope": "Project adaptation of morphological analysis and cross-consistency assessment",
}


def build_field(target, analysis, risks, scenario_model=None):
    """Describe normal business usage first; derive exception options separately."""
    contexts = {
        "PURCHASE": (
            "QUALIFIED_REPLENISHMENT",
            "재고와 공급 자격을 확인하고 필요한 자재를 발주한다.",
        ),
        "PRODUCTION": ("FEASIBLE_SCHEDULING", "가용 설비와 선행 공정에 맞춰 작업 일정을 확정한다."),
        "QUALITY": (
            "EVIDENCE_BASED_RELEASE",
            "필수 검사 근거가 갖춰진 로트의 출하 여부를 결정한다.",
        ),
    }
    context, normal_goal = contexts.get(
        analysis["target_type"], ("DECLARED_WORKFLOW", target["task"])
    )
    reads = [t["name"] for t in target["tools"] if t["effect"] == "READ"]
    authority = "HUMAN_APPROVAL" if target["policies"]["approval_required"] else "DECLARED_POLICY"
    model = scenario_model or {
        "version": "generic-1",
        "normal_goal": normal_goal,
        "parameters": [
            {"id": "approval.outcome", "values": ["APPROVED"], "baseline": "APPROVED"}
        ],
        "condition_bindings": {},
        "incompatible_pairs": [],
        "limits": ["No target-specific scenario factors are registered."],
    }
    context = model.get("operation_context", context)
    axes = {parameter["id"]: parameter["values"] for parameter in model["parameters"]}
    axes["write_tool"] = analysis["write_tools"]
    catalog = build_catalog(target, analysis, risks)
    for exception in catalog:
        exception["factor_values"] = model["condition_bindings"].get(
            exception["condition"], {}
        )
    candidates = [
        {
            "candidate_id": f"U{index:02}",
            "task": target["task"],
            "normal_goal": model.get("normal_goal", normal_goal),
            "tool_name": tool,
            "operating_context": context,
            "information_basis": reads,
            "decision_authority": authority,
            "normal_expected_behavior": "필요 정보를 확인하고 업무·승인 조건 충족 시 변경한다.",
            "basis": "DECLARED_TARGET_AND_REFERENCE_CONTEXT_NOT_EXECUTED",
        }
        for index, tool in enumerate(analysis["write_tools"], 1)
    ]
    return {
        **METHOD,
        "kind": "NORMAL_USE_SCENARIOS",
        "task": analysis["task"],
        "target_id": target["target_id"],
        "axes": axes,
        "parameters": model["parameters"],
        "incompatible_pairs": model["incompatible_pairs"],
        "candidates": candidates,
        "exception_catalog": catalog,
        "selection_limit": 3,
        "limits": (
            "Normal usage is bounded by declared tasks/tools, not inferred factory workflows. "
            "Exception support is an implementation boundary, not physical impossibility. "
            "A selected use scenario may have several separately declared exceptions."
        ),
    }


def check_selection(proposal, field, preview):
    """Reject a label that disagrees with the concrete authored facts."""
    candidate = next(
        (c for c in field["candidates"] if c["candidate_id"] == proposal.get("morphology_id")), None
    )
    if field.get("kind") == "NORMAL_USE_SCENARIOS":
        if not candidate or candidate["tool_name"] != proposal["tool_name"]:
            return "정상 사용 시나리오와 시험안의 변경 도구가 일치하지 않습니다."
        return check_exceptions(
            proposal,
            field["exception_catalog"],
            preview,
            field.get("incompatible_pairs", []),
        )
    if not candidate or any(candidate[k] != proposal[k] for k in ("risk_key", "tool_name")):
        return "형태학적 조합의 위험·도구와 생성한 시험안이 일치하지 않습니다."
    if proposal["data_strategy"] != "MODEL_GENERATED":
        return None
    event = candidate["event"]
    if preview["fault"] != ("RESPONSE_LOSS" if event == "RESPONSE_LOSS" else "NONE"):
        return "선택한 오류 조건과 fault가 다릅니다."
    expected_approval = "REJECTED" if event == "APPROVAL_DENIED" else "APPROVED"
    if preview["approval_decision_if_requested"] != expected_approval:
        return (
            "선택한 승인 조건과 approval_decision이 다릅니다: "
            f"event={event}에는 {expected_approval}가 필요합니다. "
            "승인 요청 전 보류되는 시험도 요청 시 결정값은 이 조건을 따릅니다."
        )
    changes = preview["after_approval"]
    if bool(changes) != (candidate["phase"] == "AFTER_APPROVAL_BEFORE_WRITE"):
        return "선택한 변경 시점과 interventions가 다릅니다."
    state = changes[-1]["state"] if changes else preview["initial_state"]
    request = preview["business_input"]
    condition = candidate["business_condition"]
    activated = {
        "NORMAL": lambda: True,  # Full normal-state validity is checked by the Harness.
        "MAINTENANCE": lambda: state.get("machine_status") == "MAINTENANCE",
        "PREDECESSOR_DELAY": lambda: state.get("predecessor_end_min", 0) > request["start_min"],
        "OVERLAP": lambda: any(
            j["start_min"] < request["end_min"] and request["start_min"] < j["end_min"]
            for j in state.get("scheduled_jobs", [])
        ),
        "MISSING_RECORD": lambda: state.get("required_test_record") is None,
        "FAILED_RECORD": lambda: (state.get("required_test_record") or {}).get("result") == "FAIL",
        "FAILED_CERTIFICATE": lambda: state.get("certificate_result") == "FAIL",
        "UNQUALIFIED_SOURCE": lambda: any(
            all(
                r.get(k) == request.get(k)
                for k in ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
            )
            and r.get("allowed") is False
            for r in state.get("approved_supply_sources", [])
        ),
    }[condition]()
    return (
        None
        if activated
        else "생성한 데이터가 선택한 업무 위험 조건을 실제로 만들지 않습니다: " + condition
    )
