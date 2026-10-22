"""Owner-private declarations. Registration never installs an executable adapter."""

import json
from datetime import UTC, datetime
from typing import Literal

from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictBool, model_validator
from referencing.exceptions import Unresolvable

from harness.planning import fingerprint
from harness.schemas import check_schema, validate_instance

CAPABILITIES = [
    ("inventory_read", "재고 조회", "READ"),
    ("supplier_status_read", "업체 상태 조회", "READ"),
    ("supplier_qualification_read", "공급 자격 조회", "READ"),
    ("order_read", "발주 결과 조회", "READ"),
    ("order_write", "발주 생성", "WRITE"),
    ("inspection_read", "검사 원자료 조회", "READ"),
    ("inspection_write", "검사 결과 변경", "WRITE"),
    ("machine_read", "설비 상태 조회", "READ"),
    ("routing_read", "선행 공정 조회", "READ"),
    ("schedule_write", "생산 일정 확정", "WRITE"),
    ("release_write", "출하 승인", "WRITE"),
    ("untrusted_text_read", "외부 문서 조회", "READ"),
]
CAPABILITY_OPTIONS = [{"name": n, "label": label, "effect": e} for n, label, e in CAPABILITIES]
EFFECTS = {n: e for n, _, e in CAPABILITIES}


class Declaration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Tool(Declaration):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str = Field(default="", max_length=2000)
    effect: Literal["READ", "WRITE"]
    input_schema: dict = Field(validation_alias=AliasChoices("input_schema", "inputSchema"))


class Policies(Declaration):
    approval_required: StrictBool | None = None
    max_write_retries: int | None = Field(default=None, ge=0, le=10, strict=True)


class Binding(Declaration):
    name: str
    tool_name: str
    basis: Literal["DECLARED"] = "DECLARED"


class Sample(Declaration):
    business_input: dict
    initial_state: dict


class Registration(Declaration):
    execution_runtime: str | None = Field(
        default=None, pattern=r"^(reference|external)-[a-z0-9-]{1,80}$"
    )
    name: str = Field(min_length=2, max_length=80)
    version: str = Field(min_length=1, max_length=64)
    agent_type: Literal["PURCHASE", "PRODUCTION", "QUALITY", "COMMON"]
    task: str = Field(min_length=1, max_length=1500)
    industry_context: str = Field(min_length=1, max_length=1500)
    tools: list[Tool] = Field(min_length=1, max_length=30)
    policies: Policies
    business_input_schema: dict
    sample_data: Sample
    capability_bindings: list[Binding] = Field(default_factory=list, max_length=30)
    excluded_capabilities: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def check_declarations(self):
        if len(json.dumps(self.model_dump()).encode()) > 100_000:
            raise ValueError("등록 정보는 100 KB 이하여야 합니다.")
        tools = {t.name: t for t in self.tools}
        if len(tools) != len(self.tools):
            raise ValueError("도구 이름이 중복됩니다.")
        bindings = {b.name: b for b in self.capability_bindings}
        if len(bindings) != len(self.capability_bindings):
            raise ValueError("같은 기능에 도구를 여러 개 연결할 수 없습니다.")
        for b in bindings.values():
            if b.name not in EFFECTS or b.tool_name not in tools:
                raise ValueError("알 수 없는 기능 또는 도구입니다.")
            if tools[b.tool_name].effect != EFFECTS[b.name]:
                raise ValueError("기능과 도구의 조회·변경 구분이 맞지 않습니다.")
        if set(self.excluded_capabilities) - EFFECTS.keys():
            raise ValueError("알 수 없는 제외 기능입니다.")
        if set(self.excluded_capabilities) & bindings.keys():
            raise ValueError("연결한 기능을 동시에 제외할 수 없습니다.")
        try:
            for schema in [self.business_input_schema] + [t.input_schema for t in self.tools]:
                check_schema(schema)
            validate_instance(self.business_input_schema, self.sample_data.business_input)
        except (ValidationError, SchemaError, RecursionError, Unresolvable):
            raise ValueError("입력 스키마 또는 시험 데이터 형식이 올바르지 않습니다.") from None
        return self


def declaration(body):
    result = body.model_dump(exclude={"execution_runtime"})
    if body.execution_runtime:
        result["execution_runtime"] = body.execution_runtime
    return result


def bind_runtime(body, planner, execution_profile):
    """Only an explicit selection of the installed implementation can execute."""
    if not body.execution_runtime:
        return None
    expected = planner.target_input(body.agent_type)["target"]
    actual = target_input(body)["target"]
    if (
        execution_profile.get("runtime_id") != body.execution_runtime
        or execution_profile.get("agent_type", "PURCHASE") != body.agent_type
    ):
        raise ValueError("선택한 실행기와 업무 유형이 다릅니다.")
    for key in ("task", "industry_context", "policies", "business_input_schema"):
        if actual[key] != expected[key] or any(
            v is None for v in body.policies.model_dump().values()
        ):
            raise ValueError("실행기의 업무·정책·입력 형식과 등록 정보가 다릅니다.")

    def tool_contracts(target):
        return sorted(
            [{k: t[k] for k in ("name", "effect", "input_schema")} for t in target["tools"]],
            key=lambda t: t["name"],
        )

    def capabilities(target):
        scope = target["qa_scope"]
        return (
            sorted((b["name"], b["tool_name"]) for b in scope["capabilities"]),
            set(scope["excluded_capabilities"]),
        )

    adapter = planner.adapters[expected["simulation_adapter"]]
    if tool_contracts(actual) != tool_contracts(expected) or capabilities(actual) != capabilities(
        expected
    ):
        raise ValueError("해당 업무 예시와 도구·기능 연결이 일치해야 합니다.")
    if not adapter["supports_sample"](body.sample_data.model_dump()):
        raise ValueError("시험 환경이 지원하는 입력·초기 상태를 사용하세요.")
    required = {"agent_version", "prompt_version", "model_kind", "model"}
    if not required <= execution_profile.keys():
        raise ValueError("실제 실행기의 버전 정보를 확인하지 못했습니다.")
    return {
        "runtime_id": body.execution_runtime,
        "name": ("외부 " if body.execution_runtime.startswith("external-") else "플랫폼 ")
        + {"PURCHASE": "구매", "PRODUCTION": "생산", "QUALITY": "품질"}[body.agent_type]
        + " Agent",
        "source": "OPERATOR_CONFIGURED"
        if body.execution_runtime.startswith("external-")
        else "PLATFORM_MANAGED",
        "contract_hash": fingerprint(expected),
        "execution_profile": execution_profile,
        "policy_scope": "REFERENCE_EXAMPLE_ONLY",
    }


def library_hash(root):
    return fingerprint(json.loads((root / "qa/knowledge/risk-library.json").read_text()))


def target_input(body):
    """Temporary policy values are for preflight only; unknown policies block design."""
    declared = declaration(body)
    unknown = [k for k, value in declared["policies"].items() if value is None]
    policies = {
        k: v if v is not None else {"approval_required": True, "max_write_retries": 1}[k]
        for k, v in declared["policies"].items()
    }
    target = {
        "target_id": "registered-" + fingerprint(declared)[:24],
        "target_version": body.version,
        "agent_type": body.agent_type,
        "task": body.task,
        "industry_context": body.industry_context,
        "tools": declared["tools"],
        "policies": policies,
        "simulation_adapter": "external-unbound",
        "business_input_schema": body.business_input_schema,
        "qa_scope": {
            "capabilities": declared["capability_bindings"],
            "excluded_capabilities": body.excluded_capabilities,
        },
    }
    return {"target": target, "sample_data": declared["sample_data"], "unknown_policies": unknown}


def profile(body, analysis, root, binding=None):
    declared = declaration(body)
    version = library_hash(root)
    identity = {
        **declared,
        "tools": sorted(declared["tools"], key=lambda t: t["name"]),
        "capability_bindings": sorted(declared["capability_bindings"], key=lambda b: b["name"]),
        "excluded_capabilities": sorted(set(declared["excluded_capabilities"])),
    }
    identity_data = {"input": identity, "risk_library_hash": version, "format": 1}
    if binding:
        identity_data["execution_binding"] = binding
    content_hash = fingerprint(identity_data)
    unknown = target_input(body)["unknown_policies"]
    return {
        "profile_id": "TARGET-" + content_hash[:32],
        "profile_hash": content_hash,
        "created_at": datetime.now(UTC).isoformat(),
        "name": body.name,
        "version": body.version,
        "agent_type": body.agent_type,
        "input": declared,
        "analysis": analysis,
        "risk_library_hash": version,
        "unknown_policies": unknown,
        "can_design": not unknown,
        "execution_status": "CONNECTED" if binding else "ADAPTER_REQUIRED",
        **({"execution_binding": binding} if binding else {}),
        "assurance": "USER_DECLARED_NOT_EXECUTION_VERIFIED",
    }
