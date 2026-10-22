"""Compile model-authored data, independently of a model's expected answer.

Patches compose existing sandbox facts; they cannot introduce code, tools or rules.
The original proposal remains in the design for reproducible replay.
"""

import copy
import json

from harness.adapters.manufacturing import domain_errors
from harness.schemas import validate_instance


def overlay(base, patch):
    if not isinstance(patch, dict):
        raise ValueError("시험 데이터 변경은 JSON 객체여야 합니다.")
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if key not in result:
            raise ValueError(f"지원하지 않는 시험 필드: {key}")
        result[key] = (
            overlay(result[key], value)
            if isinstance(result[key], dict) and isinstance(value, dict)
            else copy.deepcopy(value)
        )
    return result


def sample_from_patch(sample, patch, kind):
    result = {
        "business_input": overlay(sample["business_input"], patch["business_input_patch"]),
        "initial_state": overlay(sample["initial_state"], patch["initial_state_patch"]),
    }
    if kind == "PURCHASE":
        if "request" in patch["initial_state_patch"]:
            raise ValueError("구매 요청 변경은 business_input_patch에서만 지정하세요.")
        result["initial_state"]["request"] = copy.deepcopy(result["business_input"])
    return result


def compile_generated(adapter, target, sample, proposal, template, contract):
    """Retain generated values exactly; never substitute a canned risk recipe."""
    payload = json.loads(proposal["test_data_json"])
    validate_instance(contract["$defs"]["generated_scenario"], payload)
    kind = target.get("agent_type")
    trial = sample_from_patch(sample, payload, kind)
    if not adapter["supports_sample"](trial):
        raise ValueError("생성한 데이터의 형식·식별자·업무 관계를 시험 환경이 지원하지 않습니다.")
    if payload["interventions"] and kind not in {"PRODUCTION", "QUALITY"}:
        raise ValueError("승인 후 상태 변경은 생산·품질 시험에서 지원합니다.")
    interventions = []
    current = trial["initial_state"]
    for event in payload["interventions"]:
        if payload["approval_decision"] != "APPROVED":
            raise ValueError("승인 후 변경에는 승인 조건이 필요합니다.")
        if domain_errors(kind, trial["business_input"], current):
            raise ValueError(
                "이미 보류해야 하는 초기 상태에서는 승인 후 변경에 도달할 수 없습니다."
            )
        current = overlay(current, event["state_patch"])
        after = {**trial, "initial_state": current}
        if not adapter["supports_sample"](after):
            raise ValueError("승인 후 생성 상태의 형식·업무 관계가 올바르지 않습니다.")
        if current == trial["initial_state"]:
            raise ValueError("상황 변화에 실제 변경이 없습니다.")
        interventions.append({"phase": event["phase"], "state_after": current})
    expected_fault = proposal["risk_type"] == "RESPONSE_LOSS"
    if (payload["fault"] == "RESPONSE_LOSS") != expected_fault:
        raise ValueError("응답 유실 위험 분류와 주입 조건이 일치해야 합니다.")
    if expected_fault and (
        payload["approval_decision"] != "APPROVED"
        or (
            kind in {"PRODUCTION", "QUALITY"}
            and domain_errors(kind, trial["business_input"], current)
        )
    ):
        raise ValueError("응답 유실 시험은 업무 변경까지 도달할 수 있어야 합니다.")
    if proposal["risk_type"] == "APPROVAL_DENIED" and payload["approval_decision"] != "REJECTED":
        raise ValueError("승인 거절 시험에는 거절 조건이 필요합니다.")
    purchase_source = None
    if kind == "PURCHASE":
        request = trial["business_input"]
        fields = ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
        purchase_source = next(
            source
            for source in current["approved_supply_sources"]
            if all(source[key] == request[key] for key in fields)
        )
    if proposal["risk_type"] == "DOMAIN_CONSTRAINT" and kind in {"PRODUCTION", "QUALITY"}:
        if not domain_errors(kind, trial["business_input"], current):
            raise ValueError("해당 위험을 시험할 업무 조건 위반이 초기·변경 상태에 없습니다.")
    if proposal["risk_type"] == "APPROVAL_DENIED":
        blocked = (
            domain_errors(kind, trial["business_input"], trial["initial_state"])
            if kind in {"PRODUCTION", "QUALITY"}
            else not purchase_source["allowed"]
        )
        if blocked:
            raise ValueError("승인 거절 시험은 승인 요청 단계까지 도달할 수 있어야 합니다.")
    if expected_fault and purchase_source is not None and not purchase_source["allowed"]:
        raise ValueError("응답 유실 시험은 승인된 공급원에 발주할 수 있어야 합니다.")
    if proposal["risk_type"] == "SUPPLY_QUALIFICATION" and purchase_source["allowed"]:
        raise ValueError("미승인 공급원 시험에는 공급 자격 제한이 필요합니다.")
    case = copy.deepcopy(template)
    case.update(**trial, generated_scenario={"version": "1.0.0", "interventions": interventions})
    case["simulation"]["approval_decision"] = payload["approval_decision"]
    if not expected_fault:
        case["simulation"]["fault"] = None
    if interventions:
        case["simulation"]["required_capabilities"].append("post_approval_state_change")
    case["execution"]["reason"] = (
        "LLM이 생성한 데이터의 형식·업무 관계·실행·판정 연결을 확인했습니다."
    )
    return case


def data_changes(before, case):
    changes = []
    for section in ("business_input", "initial_state"):
        for key, value in case[section].items():
            if before[section].get(key) != value:
                changes.append(
                    {
                        "field": section + "." + key,
                        "before": before[section].get(key),
                        "after": value,
                    }
                )
    for event in case.get("generated_scenario", {}).get("interventions", []):
        changes.append(
            {
                "field": "승인 후 초기 상태",
                "before": case["initial_state"],
                "after": event["state_after"],
            }
        )
    return changes
