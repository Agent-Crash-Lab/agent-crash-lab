"""Validate declared targets and classify applicable risks without model calls."""

import json

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource


def deny_schema_resource(uri):
    raise NoSuchResource(ref=uri)


def validate_input(settings, body):
    if len(json.dumps(body.model_dump()).encode()) > 100_000:
        raise ValueError("Design input too large")

    # Descriptions are data. Schema imports must never fetch external resources.
    def local_schema(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise ValueError("Only local schema references are supported")
                if key in {"$id", "$schema"}:
                    continue
                local_schema(item)
        elif isinstance(value, list):
            for item in value:
                local_schema(item)

    root = settings.agent_project_root
    contract = json.loads((root / "qa/contracts/qa.schema.json").read_text())
    for kind, value in (("target", body.target), ("sample", body.sample_data)):
        Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": contract["$defs"]}).validate(
            value
        )
    schemas = [body.target["business_input_schema"]] + [
        t["input_schema"] for t in body.target["tools"]
    ]
    for schema in schemas:
        local_schema(schema)
        Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        body.target["business_input_schema"], registry=Registry(retrieve=deny_schema_resource)
    ).validate(body.sample_data["business_input"])


def analyze_description(settings, body, *, library=None):
    validate_input(settings, body)
    if library is None:
        library = json.loads(
            (settings.agent_project_root / "qa/knowledge/risk-library.json").read_text()
        )
    analysis = analyze(body.target, body.sample_data)
    capabilities, screening = screen_risks(body.target, analysis, library)
    unknown = set(getattr(body, "unknown_policies", []))
    analysis["declared_policies"] = {
        key: None if key in unknown else value for key, value in body.target["policies"].items()
    }
    by_key = {r["risk_key"]: r for r in library["risks"]}
    for row in screening:
        risk = by_key[row["risk_key"]]
        needed = (risk["requires_approval"] and "approval_required" in unknown) or (
            risk["requires_retry"] and "max_write_retries" in unknown
        )
        if needed and row["status"] != "OUT_OF_SCOPE":
            row.update(
                status="NEEDS_INFORMATION", reason="승인 또는 재시도 정책을 확인해야 합니다."
            )
    analysis.update(capabilities=capabilities, risk_screening=screening)
    operations = json.loads(
        (settings.agent_project_root / "qa/knowledge/manufacturing-operations.json").read_text()
    )
    analysis["manufacturing_context"] = {
        k: operations[k] for k in ("version", "domain_id", "scope", "positioning", "features")
    }
    analysis["manufacturing_context"]["generation_rules_en"] = operations["generation_rules_en"]
    analysis["manufacturing_context"]["scenario_examples"] = [
        s for s in operations["scenarios"] if s["agent_type"] == analysis["target_type"]
    ]
    if unknown:
        analysis["unknowns"].append("입력하지 않은 정책은 추정하지 않으며 시험 설계를 보류합니다.")
    return analysis


def analyze(target, sample):
    names = set(sample["business_input"])
    signatures = {
        "PURCHASE": {"supplier_id", "part_id"},
        "PRODUCTION": {"machine_id", "operation_id"},
        "QUALITY": {"lot_id", "inspection_id"},
    }
    matches = [role for role, fields in signatures.items() if fields <= names]
    declared = target.get("agent_type")
    role = declared or (matches[0] if len(matches) == 1 else "COMMON")
    writes = [t["name"] for t in target["tools"] if t["effect"] == "WRITE"]
    return {
        "target_type": role,
        "classification_basis": sorted(names),
        "classification_method": (
            "DECLARED_TYPE"
            if declared
            else "INPUT_FIELD_SIGNATURE"
            if role != "COMMON"
            else "UNKNOWN"
        ),
        "task": target["task"],
        "tools": [
            {
                "name": t["name"],
                "effect": t["effect"],
                "required_inputs": t["input_schema"].get("required", []),
                "description": t.get("description", ""),
            }
            for t in target["tools"]
        ],
        "write_tools": writes,
        "declared_policies": target["policies"],
        "unknowns": [
            "소스 코드·실행 경로·실제 권한은 분석하지 않았습니다.",
            "등록한 업무 유형을 우선 사용하고, 실제 기능은 도구별로 확인합니다.",
            "문서의 정책 제안은 회사에서 채택한 판정 규칙이 아닙니다.",
        ],
    }


def screen_risks(target, analysis, library):
    tools = {t["name"]: t for t in target["tools"]}
    declared = target.get("qa_scope", {})
    capabilities = {"state_write"} if analysis["write_tools"] else set()
    excluded = set(declared.get("excluded_capabilities", []))
    if not analysis["write_tools"]:
        excluded.add("state_write")
    for item in declared.get("capabilities", []):
        tool = tools.get(item["tool_name"])
        effect = "WRITE" if item["name"].endswith("_write") else "READ"
        if tool is None or tool["effect"] != effect or item["name"] in excluded:
            raise ValueError("Capability binding conflicts with declared tool or exclusions")
        capabilities.add(item["name"])
    screening = []
    for risk in library["risks"]:
        missing = sorted(set(risk["required_capabilities"]) - capabilities)
        disabled = (risk["requires_approval"] and not target["policies"]["approval_required"]) or (
            risk["requires_retry"] and target["policies"]["max_write_retries"] < 1
        )
        if disabled or set(missing) & excluded:
            status, reason = (
                "OUT_OF_SCOPE",
                "필요한 기능이 제외됐거나 해당 승인·재시도 조건이 없습니다.",
            )
        elif missing:
            status, reason = (
                "NEEDS_INFORMATION",
                "필요 기능을 확인할 설명이나 도구 연결 정보가 부족합니다.",
            )
        else:
            status, reason = (
                "APPLICABLE",
                "제공된 기능·도구·정책에서 해당 위험을 시험할 수 있습니다.",
            )
        screening.append(
            {
                "risk_key": risk["risk_key"],
                "title": risk["title"],
                "status": status,
                "reason": reason,
                "missing_capabilities": missing,
                "reference_source_ids": risk["reference_source_ids"],
            }
        )
    return sorted(capabilities), screening
