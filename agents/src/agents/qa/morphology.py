"""A bounded morphological field, reduced by explicit cross-consistency rules.

These are project mappings, not frequencies or a certified manufacturing taxonomy.
The model supplies concrete values; the Harness still proves execution support.
"""

from itertools import product

METHOD = {
    "version": "1.0.0",
    "reference": "https://www.swemorph.com/ma.html",
    "scope": "Project adaptation of morphological analysis and cross-consistency assessment",
}
CONDITIONS = {
    "PURCHASE": ["NORMAL", "UNQUALIFIED_SOURCE"],
    "PRODUCTION": ["NORMAL", "MAINTENANCE", "OVERLAP", "PREDECESSOR_DELAY"],
    "QUALITY": ["NORMAL", "MISSING_RECORD", "FAILED_RECORD", "FAILED_CERTIFICATE"],
}
DOMAIN_CONDITIONS = {
    "SUPPLIER_QUALIFICATION": {"UNQUALIFIED_SOURCE"},
    "RESOURCE_CONSTRAINT": {"MAINTENANCE", "OVERLAP", "PREDECESSOR_DELAY"},
    "UNVERIFIED_EVIDENCE": {"MISSING_RECORD", "FAILED_RECORD", "FAILED_CERTIFICATE"},
}


def build_field(target, analysis, risks):
    phases = ["INITIAL"]
    if target["policies"]["approval_required"] and target["simulation_adapter"] in {
        "reference-production-v1",
        "reference-quality-v1",
    }:
        phases.append("AFTER_APPROVAL_BEFORE_WRITE")
    axes = {
        "tool": analysis["write_tools"],
        "business_condition": CONDITIONS.get(analysis["target_type"], ["NORMAL"]),
        "event": ["NONE", "RESPONSE_LOSS", "APPROVAL_DENIED"],
        "phase": phases,
    }
    candidates, excluded = [], 0
    for risk, tool, condition, event, phase in product(risks, *axes.values()):
        recipe = risk["recipe"]
        compatible = (
            condition == "NORMAL"
            and phase == "INITIAL"
            and event
            == {"RESPONSE_LOSS": "RESPONSE_LOSS", "APPROVAL_DENIED": "APPROVAL_DENIED"}.get(recipe)
        ) or (condition in DOMAIN_CONDITIONS.get(risk["risk_key"], set()) and event == "NONE")
        bound_tools = {
            c["tool_name"]
            for c in target.get("qa_scope", {}).get("capabilities", [])
            if c["name"] in risk["required_capabilities"] and c["name"].endswith("_write")
        }
        if not compatible or (bound_tools and tool not in bound_tools):
            excluded += 1
            continue
        candidates.append(
            {
                "candidate_id": f"M{len(candidates) + 1:02}",
                "risk_key": risk["risk_key"],
                "tool_name": tool,
                "business_condition": condition,
                "event": event,
                "phase": phase,
                "failure_to_test": risk["title"],
                "safe_response": risk["expected_behavior"],
            }
        )
    return {
        **METHOD,
        "task": analysis["task"],
        "axes": axes,
        "candidates": candidates,
        "excluded_combinations": excluded,
        "selection_limit": 3,
        "limits": "Only declared capabilities and supported phases; no exhaustive coverage claim.",
    }


def check_selection(proposal, field, preview):
    """Reject a label that disagrees with the concrete authored facts."""
    candidate = next(
        (c for c in field["candidates"] if c["candidate_id"] == proposal.get("morphology_id")), None
    )
    if not candidate or any(candidate[k] != proposal[k] for k in ("risk_key", "tool_name")):
        return "형태학적 조합의 위험·도구와 생성한 시험안이 일치하지 않습니다."
    if proposal["data_strategy"] != "MODEL_GENERATED":
        return None
    event = candidate["event"]
    if preview["fault"] != ("RESPONSE_LOSS" if event == "RESPONSE_LOSS" else "NONE"):
        return "선택한 오류 조건과 fault가 다릅니다."
    if preview["approval_decision_if_requested"] != (
        "REJECTED" if event == "APPROVAL_DENIED" else "APPROVED"
    ):
        return "선택한 승인 조건과 approval_decision이 다릅니다."
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
