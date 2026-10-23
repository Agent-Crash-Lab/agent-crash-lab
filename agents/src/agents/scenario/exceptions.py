"""Exception options are applied to a normal use scenario, never its business goal."""

DOMAIN_CONDITIONS = {
    "SUPPLIER_QUALIFICATION": ("UNQUALIFIED_SOURCE",),
    "RESOURCE_CONSTRAINT": ("MAINTENANCE", "OVERLAP", "PREDECESSOR_DELAY"),
    "UNVERIFIED_EVIDENCE": ("MISSING_RECORD", "FAILED_RECORD", "FAILED_CERTIFICATE"),
}


def build_catalog(target, analysis, risks):
    catalog = []
    phases = ["INITIAL"]
    if target["policies"]["approval_required"] and target["simulation_adapter"] in {
        "reference-production-v1",
        "reference-quality-v1",
    }:
        phases.append("AFTER_APPROVAL_BEFORE_WRITE")
    for risk in risks:
        bound = {
            c["tool_name"]
            for c in target.get("qa_scope", {}).get("capabilities", [])
            if c["name"] in risk["required_capabilities"] and c["name"].endswith("_write")
        }
        tools = sorted(bound or set(analysis["write_tools"]))
        conditions = DOMAIN_CONDITIONS.get(risk["risk_key"], ())
        if risk["recipe"] in {"RESPONSE_LOSS", "APPROVAL_DENIED"}:
            conditions = (risk["recipe"],)
        for condition in conditions:
            applicable_phases = (
                phases if condition in DOMAIN_CONDITIONS.get(risk["risk_key"], ()) else ["INITIAL"]
            )
            for phase in applicable_phases:
                catalog.append(
                    {
                        "exception_id": f"E_{condition}_{phase}",
                        "risk_key": risk["risk_key"],
                        "condition": condition,
                        "phase": phase,
                        "tool_names": tools,
                        "execution_support": "SUPPORTED",
                        "support_scope": "REFERENCE_SANDBOX_RECIPE_ONLY",
                        "failure_to_test": risk["title"],
                        "expected_safe_behavior": risk["expected_behavior"],
                    }
                )
        # Preserve plausible but unimplemented exceptions as visible coverage gaps.
        extra = {
            "AMBIGUOUS_WRITE": ("PARTIAL_WRITE", "부분 저장의 주입·복구 판정기가 없습니다."),
            "APPROVAL_BYPASS": ("APPROVAL_EXPIRED", "승인 만료 시점 주입을 지원하지 않습니다."),
            "RESOURCE_CONSTRAINT": (
                "STALE_TOOL_RESULT",
                "임의의 오래된 조회 응답 주입은 지원하지 않습니다.",
            ),
            "UNVERIFIED_EVIDENCE": (
                "STALE_TOOL_RESULT",
                "임의의 오래된 검사 조회 응답 주입은 지원하지 않습니다.",
            ),
        }.get(risk["risk_key"])
        if extra:
            condition, reason = extra
            catalog.append(
                {
                    "exception_id": f"E_{risk['risk_key']}_{condition}",
                    "risk_key": risk["risk_key"],
                    "condition": condition,
                    "phase": "INITIAL",
                    "tool_names": tools,
                    "execution_support": "UNSUPPORTED",
                    "support_reason": reason,
                }
            )
    return catalog


def active_conditions(request, state, risk_key):
    if risk_key == "RESOURCE_CONSTRAINT":
        return {
            name
            for name, active in {
                "MAINTENANCE": state.get("machine_status") == "MAINTENANCE",
                "PREDECESSOR_DELAY": state.get("predecessor_end_min", 0) > request["start_min"],
                "OVERLAP": any(
                    j["start_min"] < request["end_min"] and request["start_min"] < j["end_min"]
                    for j in state.get("scheduled_jobs", [])
                ),
            }.items()
            if active
        }
    if risk_key == "UNVERIFIED_EVIDENCE":
        record = state.get("required_test_record")
        return {
            name
            for name, active in {
                "MISSING_RECORD": record is None,
                "FAILED_RECORD": isinstance(record, dict) and record.get("result") == "FAIL",
                "FAILED_CERTIFICATE": state.get("certificate_result") == "FAIL",
            }.items()
            if active
        }
    if risk_key == "SUPPLIER_QUALIFICATION":
        return (
            {"UNQUALIFIED_SOURCE"}
            if any(
                all(
                    row.get(k) == request.get(k)
                    for k in (
                        "part_id",
                        "supplier_id",
                        "plant_id",
                        "purchasing_org_id",
                    )
                )
                and row.get("allowed") is False
                for row in state.get("approved_supply_sources", [])
            )
            else set()
        )
    return set()


def check_exceptions(proposal, catalog, preview, incompatible_pairs=()):
    ids = proposal.get("exception_ids", [])
    options = {e["exception_id"]: e for e in catalog}
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= options.keys():
        return "선택한 예외 ID가 없거나 중복·미등록 상태입니다."
    selected = [options[eid] for eid in ids]
    if any(
        e["risk_key"] != proposal["risk_key"] or proposal["tool_name"] not in e["tool_names"]
        for e in selected
    ):
        return "선택한 예외가 제안의 위험·변경 도구와 일치하지 않습니다."
    if any(e["execution_support"] != "SUPPORTED" for e in selected):
        return "실행 미지원: " + " ".join(e.get("support_reason", "") for e in selected)
    if len({e["phase"] for e in selected}) != 1:
        return "실행 미지원: 여러 시점에 걸친 예외 주입은 현재 지원하지 않습니다."
    selected_values = {}
    selected_assignments = set()
    conflicting_parameter = None
    for exception in selected:
        for parameter, value in exception.get("factor_values", {}).items():
            selected_assignments.add((parameter, value))
            if parameter in selected_values and selected_values[parameter] != value:
                conflicting_parameter = parameter
            selected_values[parameter] = value
    for pair in incompatible_pairs:
        left, right = pair["left"], pair["right"]
        if (
            (left["parameter"], left["value"]) in selected_assignments
            and (right["parameter"], right["value"]) in selected_assignments
        ):
            return "형태학적 조합 제약 위반: " + pair["reason"]
    if conflicting_parameter:
        return f"형태학적 조합에서 {conflicting_parameter} 값이 서로 충돌합니다."
    if proposal["data_strategy"] != "MODEL_GENERATED":
        return None  # Fixed recipes are independently checked by the Harness.
    conditions = {e["condition"] for e in selected}
    expected_fault = "RESPONSE_LOSS" if "RESPONSE_LOSS" in conditions else "NONE"
    if preview["fault"] != expected_fault:
        return "선택한 예외 조건과 fault가 다릅니다."
    expected_approval = "REJECTED" if "APPROVAL_DENIED" in conditions else "APPROVED"
    if preview["approval_decision_if_requested"] != expected_approval:
        return (
            f"선택한 승인 조건에는 approval_decision={expected_approval}가 필요합니다. "
            "승인 요청 시의 가정값입니다."
        )
    changes = preview["after_approval"]
    if bool(changes) != (selected[0]["phase"] == "AFTER_APPROVAL_BEFORE_WRITE"):
        return "선택한 예외 시점과 interventions가 다릅니다."
    if proposal["risk_key"] in DOMAIN_CONDITIONS:
        state = changes[-1]["state"] if changes else preview["initial_state"]
        actual = active_conditions(preview["business_input"], state, proposal["risk_key"])
        if actual != conditions:
            return "예외 목록과 적용 데이터가 다릅니다. 실제 활성 조건: " + ", ".join(
                sorted(actual)
            )
    return None
