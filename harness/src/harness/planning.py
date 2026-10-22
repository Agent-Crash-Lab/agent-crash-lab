"""Target → capability analysis → risk templates → concrete simulation plan.

This is deterministic planning, not an LLM safety verdict. Only a registered,
matching execution adapter can turn a proposed case into an executable test.
"""

import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from harness.adapters import registered_adapters
from harness.evaluation import bind_strategy
from harness.generation import compile_generated, data_changes
from harness.schemas import check_schema, validate_instance


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class QaPlanner:
    def __init__(self, root: Path):
        self.root = root
        self.config = self.read("config/qa-runtime.json")
        self.config = {**self.read(self.config["references"]["simulation"]), **self.config}
        refs = self.config["references"]
        self.contract = self.read(refs["qa_contract"])
        self.patterns = self.read(refs["risk_patterns"])
        self.test_policy = self.read("qa/knowledge/test-policy.json")
        self.target_examples = self.read("qa/examples/manufacturing-targets.json")
        self.risk_library = self.read("qa/knowledge/risk-library.json")
        self.operations = self.read("qa/knowledge/manufacturing-operations.json")
        self.source_records = {
            r["source_id"]: r for r in self.read("qa/knowledge/sources-collected.json")["records"]
        }
        adapters = registered_adapters(root, self.config)
        reference = adapters[self.config["target"]["simulation_adapter"]]
        self.reference_target = reference.target
        self.reference_sample = reference.sample
        # A descriptor supplied by a caller cannot register an adapter or claim its capabilities.
        self.adapters = {
            name: {
                "target": adapter.target,
                "target_hash": fingerprint(adapter.target),
                "data_hash": fingerprint(adapter.sample),
                "capabilities": adapter.capabilities,
                "tests": adapter.tests,
                "rules_by_test": adapter.rules_by_test,
                "supports_sample": adapter.supports_sample,
                "design_sample": adapter.design_sample,
                "prepare_case": adapter.prepare_case,
            }
            for name, adapter in adapters.items()
        }

    def target_input(self, kind):
        adapter = self.adapters.get(f"reference-{kind.lower()}-v1")
        if adapter:
            if kind == "PURCHASE":
                sample = self.reference_sample
            else:
                sample = self.target_examples[kind]["sample_data"]
            return {"target": adapter["target"], "sample_data": sample}
        return {key: self.target_examples[kind][key] for key in ("target", "sample_data")}

    def target_types(self):
        result = []
        for kind, item in self.target_examples.items():
            reference = self.target_input(kind)
            plan = self.build(reference["target"], reference["sample_data"])
            result.append(
                {
                    "type_id": kind,
                    **{k: item[k] for k in ("name", "description", "checks")},
                    "execution": "READY"
                    if any(c["execution"]["status"] == "READY" for c in plan["cases"])
                    else "DESIGN_ONLY",
                }
            )
        return result

    def read(self, path):
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError("QA reference must remain inside the project")
        return json.loads(resolved.read_text(encoding="utf-8"))

    def validate(self, definition, value):
        Draft202012Validator(
            {"$ref": f"#/$defs/{definition}", "$defs": self.contract["$defs"]}
        ).validate(value)

    def build(self, target=None, sample=None, knowledge_evidence=None):
        if target is None:
            if sample is not None:
                raise ValueError("Custom sample data requires an explicit target")
            target, sample = self.reference_target, self.reference_sample
        elif sample is None:
            raise ValueError("An explicit target requires its own sample data")
        self.validate("target", target)
        self.validate("sample", sample)
        names = [tool["name"] for tool in target["tools"]]
        if len(names) != len(set(names)):
            raise ValueError("Target tool names must be unique")
        for tool in target["tools"]:
            check_schema(tool["input_schema"])
        check_schema(target["business_input_schema"])
        validate_instance(target["business_input_schema"], sample["business_input"])

        target_hash, data_hash = fingerprint(target), fingerprint(sample)
        adapter = self.adapters.get(target["simulation_adapter"])
        registered = bool(
            adapter and adapter["target_hash"] == target_hash and adapter["supports_sample"](sample)
        )
        writes = [tool for tool in target["tools"] if tool["effect"] == "WRITE"]
        features = {"write"} if writes else {"read_only"}
        if any(
            c["name"] == "supplier_qualification_read"
            for c in target.get("qa_scope", {}).get("capabilities", [])
        ):
            features.add("supplier_qualification")
        if target.get("agent_type") in {"PRODUCTION", "QUALITY"}:
            features.add(target["agent_type"].lower())
        if target["policies"]["approval_required"]:
            features.add("approval")
        cases = []
        tools = writes or target["tools"][:1]
        for tool in tools:
            for pattern in self.patterns["patterns"]:
                if not set(pattern["requires"]) <= features:
                    continue
                missing = sorted(
                    set(pattern["simulation_capabilities"])
                    - (adapter["capabilities"] if registered else set())
                )
                test_id = adapter["tests"].get(pattern["risk_id"]) if registered else None
                prepared = (
                    adapter["prepare_case"](pattern["risk_id"], sample) if registered else sample
                )
                ready = registered and prepared is not None and not missing and test_id is not None
                prepared = prepared or sample
                simulation = {
                    "adapter_id": target["simulation_adapter"],
                    "approval_decision": (
                        pattern["approval_decision"] if "approval" in features else None
                    ),
                    "fault": None,
                    "required_capabilities": pattern["simulation_capabilities"],
                    "max_write_retries": target["policies"]["max_write_retries"],
                }
                if pattern["fault_trigger"]:
                    simulation["fault"] = {
                        "tool_name": tool["name"],
                        "trigger": pattern["fault_trigger"],
                        "max_applied_count": 1,
                        "target_error_code": "TOOL_TIMEOUT",
                    }
                cases.append(
                    {
                        "case_id": f"{target['target_id']}:{tool['name']}:{pattern['risk_id']}",
                        "risk_id": pattern["risk_id"],
                        "hypothesis": pattern["hypothesis"].replace("{tool}", tool["name"]),
                        "business_input": copy.deepcopy(prepared["business_input"]),
                        "initial_state": copy.deepcopy(prepared["initial_state"]),
                        "data_hash": fingerprint(prepared),
                        "simulation": simulation,
                        "assertions": copy.deepcopy(pattern["assertions"]),
                        "execution": {
                            "status": "READY" if ready else "UNSUPPORTED",
                            "registered_test_id": test_id if ready else None,
                            "rule_ids": adapter["rules_by_test"][test_id] if ready else [],
                            "missing_capabilities": missing,
                            "reason": (
                                "Registered simulator and code evaluator available"
                                if ready
                                else "Requires a registered target/data adapter and code evaluator"
                            ),
                        },
                        "actual_result": None,
                    }
                )
        plan = {
            "schema_version": "1.0.0",
            "target_id": target["target_id"],
            "target_version": target["target_version"],
            "target_hash": target_hash,
            "data_hash": data_hash,
            "knowledge_version": self.patterns["version"],
            "analysis": {
                "method": "STRUCTURED_CAPABILITY_ANALYSIS",
                "task": target["task"],
                "industry_context": target["industry_context"],
                "write_tools": [tool["name"] for tool in writes],
                "approval_required": "approval" in features,
                "limitations": [
                    "Only configured risk templates are covered; domain safety is not certified.",
                    "READ/WRITE effects and policies are supplied metadata, not code analysis.",
                    "READY describes available execution support, not a passing QA result.",
                ],
            },
            "cases": cases,
        }
        context = {
            k: copy.deepcopy(self.operations[k])
            for k in (
                "version",
                "domain_id",
                "name",
                "scope",
                "positioning",
                "features",
                "interpretation",
            )
        }
        context["background_sources"] = [
            {k: self.source_records[sid][k] for k in ("source_id", "title", "url")}
            for sid in sorted({sid for f in context["features"] for sid in f["source_ids"]})
        ]
        plan["analysis"]["manufacturing_context"] = context
        for case in cases:
            case["manufacturing_context"] = copy.deepcopy(context)
        if knowledge_evidence:
            plan["knowledge_evidence"] = copy.deepcopy(knowledge_evidence)
            plan["analysis"]["limitations"].append(
                "Retrieved references provide context; cases still use registered risk templates."
            )
        if target.get("agent_type") in {"PRODUCTION", "QUALITY"}:
            plan["base_sample"] = copy.deepcopy(sample)
        plan["plan_id"] = "QAP-" + fingerprint(plan)[:24]
        self.validate("plan", plan)
        return plan

    def rebuild(self, plan, case=None):
        target = next(
            (
                a["target"]
                for a in self.adapters.values()
                if a["target_hash"] == plan["target_hash"]
            ),
            self.reference_target,
        )
        if plan.get("design"):
            return self.build_designed(target, plan["design"]["base_sample"], plan["design"])
        sample = {k: (case or plan["cases"][0])[k] for k in ("business_input", "initial_state")}
        return self.build(target, plan.get("base_sample", sample), plan.get("knowledge_evidence"))

    def build_designed(self, target, sample, design):
        """Compile proposals into trusted recipes; a model cannot register an evaluator."""
        plan = self.build(target, sample)
        strategic = design.get("version") in {"3.0.0", "4.0.0"}
        modern = strategic or design.get("version") == "2.0.0"
        if strategic and (
            design.get("test_policy_hash") != fingerprint(self.test_policy)
            or design.get("test_policy_version") != self.test_policy["version"]
        ):
            raise ValueError("Test policy changed; design a new plan")
        reviews = {r["proposal_id"]: r for r in design.get("reviews", [])}
        if strategic and (
            len(reviews) != len(design["proposals"])
            or set(reviews) != {p["proposal_id"] for p in design["proposals"]}
        ):
            raise ValueError("Incomplete design review")
        if strategic:
            for case in plan["cases"]:
                if case["risk_id"] == "CONTROL_BASELINE":
                    case["evaluation_strategy"] = bind_strategy(self.test_policy, case)
        if modern and (
            design.get("risk_library_hash") != fingerprint(self.risk_library)
            or design.get("risk_library_version") != self.risk_library["version"]
        ):
            raise ValueError("Risk library changed; rebuild design")
        library = {r["risk_key"]: r for r in self.risk_library["risks"]}
        applicable = {
            r["risk_key"]
            for r in design.get("analysis", {}).get("risk_screening", [])
            if r["status"] == "APPLICABLE"
        }
        adapter = self.adapters.get(target["simulation_adapter"])
        matching = bool(adapter and adapter["target_hash"] == fingerprint(target))
        sources = {s["document_id"]: s for s in design["sources"]}
        proposal_ids = set()
        if len(design["proposals"]) > 3:
            raise ValueError("Too many design proposals")
        for proposal in design["proposals"]:
            pid = proposal["proposal_id"]
            if pid in proposal_ids or proposal["tool_name"] not in plan["analysis"]["write_tools"]:
                raise ValueError("Invalid proposal identity or tool")
            proposal_ids.add(pid)
            if not set(proposal["evidence_ids"]) <= sources.keys():
                raise ValueError("Unretrieved design source")
            risk = library.get(proposal.get("risk_key"))
            if modern and (
                risk is None
                or risk["risk_key"] not in applicable
                or risk["recipe"] != proposal["risk_type"]
            ):
                raise ValueError("Risk proposal is outside validated scope")
            if modern:
                for doc_id in proposal["evidence_ids"]:
                    hit = sources[doc_id]
                    record = self.source_records.get(hit["source_id"])
                    if (
                        record is None
                        or hit.get("source_type") != record["source_type"]
                        or risk["risk_key"] not in record["risk_types"]
                    ):
                        raise ValueError("Evidence category or risk mismatch")
            facts = json.loads(proposal["test_data_json"])
            if not isinstance(facts, dict):
                raise ValueError("Proposed facts must be an object")
            risk_id = {
                "RESPONSE_LOSS": "POST_COMMIT_RESPONSE_LOSS",
                "APPROVAL_DENIED": "APPROVAL_DENIED",
                "SUPPLY_QUALIFICATION": "UNQUALIFIED_SUPPLIER",
                "DOMAIN_CONSTRAINT": {
                    "PRODUCTION": "RESOURCE_CONSTRAINT",
                    "QUALITY": "UNVERIFIED_EVIDENCE",
                }.get(target.get("agent_type")),
            }.get(proposal["risk_type"])
            trial = copy.deepcopy(sample)
            generated = proposal["data_strategy"] == "MODEL_GENERATED"
            if proposal["data_strategy"] not in {"UNCHANGED", "MODEL_GENERATED"}:
                trial = (
                    adapter["design_sample"](proposal["data_strategy"], sample)
                    if matching
                    else None
                )
            pattern_case = None
            if trial is not None and risk_id:
                pattern_case = next(
                    (
                        c
                        for c in self.build(target, trial)["cases"]
                        if c["risk_id"] == risk_id and f":{proposal['tool_name']}:" in c["case_id"]
                    ),
                    None,
                )
            if pattern_case:
                case = copy.deepcopy(pattern_case)
            else:
                case = {
                    "risk_id": "DESIGN_DOMAIN_CONSTRAINT",
                    "business_input": copy.deepcopy(sample["business_input"]),
                    "initial_state": copy.deepcopy(sample["initial_state"]),
                    "simulation": {
                        "adapter_id": target["simulation_adapter"],
                        "approval_decision": None,
                        "fault": None,
                        "required_capabilities": [
                            "domain_state_injection",
                            "domain_rule_evaluator",
                        ],
                        "max_write_retries": target["policies"]["max_write_retries"],
                    },
                    "assertions": ["PROPOSED_POLICY_REQUIRES_CODE_EVALUATOR"],
                    "execution": {
                        "status": "UNSUPPORTED",
                        "registered_test_id": None,
                        "rule_ids": [],
                        "missing_capabilities": ["domain_state_injection", "domain_rule_evaluator"],
                        "reason": "업무 조건 주입·관측·정책 채택·판정 코드 연결이 필요합니다.",
                    },
                    "actual_result": None,
                }
            if generated:
                if design.get("version") != "4.0.0" or not modern:
                    raise ValueError("Generated data requires versioned policy review")
                try:
                    if not matching or not pattern_case:
                        raise ValueError("생성 데이터를 실행·판정할 어댑터가 없습니다.")
                    case = compile_generated(
                        adapter, target, sample, proposal, pattern_case, self.contract
                    )
                except (ValueError, KeyError, TypeError, StopIteration, ValidationError) as exc:
                    case["execution"].update(
                        status="UNSUPPORTED",
                        registered_test_id=None,
                        rule_ids=[],
                        missing_capabilities=["generated_data_validation"],
                        reason=str(exc)[:250],
                    )
            if not proposal["evidence_ids"]:
                case["execution"] = {
                    "status": "UNSUPPORTED",
                    "registered_test_id": None,
                    "rule_ids": [],
                    "missing_capabilities": ["supporting_evidence"],
                    "reason": "이 위험을 뒷받침할 문서 근거를 찾지 못했습니다.",
                }
            evidence_groups = {
                kind: [] for kind in ("RESEARCH", "INCIDENT", "TECHNICAL", "PROJECT_POLICY")
            }
            adopted = []
            if modern:
                for doc_id in proposal["evidence_ids"]:
                    hit = sources[doc_id]
                    record = self.source_records[hit["source_id"]]
                    evidence_groups[record["source_type"]].append(hit["source_id"])
                    if (
                        record["source_type"] == "PROJECT_POLICY"
                        and hit["source_id"] in risk["policy_ids"]
                        and record.get("policy_status") == "REFERENCE_ADOPTED"
                        and target["simulation_adapter"] in record.get("adopted_adapters", [])
                    ):
                        adopted.append(hit["source_id"])
                missing_evidence = []
                if not evidence_groups["RESEARCH"]:
                    missing_evidence.append("research_evidence")
                if not adopted:
                    missing_evidence.append("adopted_business_policy")
                if missing_evidence:
                    case["execution"].update(
                        status="UNSUPPORTED",
                        registered_test_id=None,
                        rule_ids=[],
                        missing_capabilities=sorted(
                            set(case["execution"]["missing_capabilities"] + missing_evidence)
                        ),
                        reason="연구·채택 정책 또는 실행·판정 연결이 부족합니다.",
                    )
                case["applicability"] = "APPLICABLE"
            case["case_id"] = f"{target['target_id']}:{proposal['tool_name']}:DESIGN_{pid}"
            case["hypothesis"] = (
                proposal["title"]
                if strategic
                else proposal["title"] + ": " + proposal["failure_mode"]
            )
            data_identity = {k: case[k] for k in ("business_input", "initial_state")}
            if generated:
                data_identity.update(
                    simulation=case["simulation"], generated_scenario=case.get("generated_scenario")
                )
            case["data_hash"] = fingerprint(data_identity)
            case["design_basis"] = {
                "proposal_id": pid,
                "risk_key": proposal.get("risk_key"),
                "evidence_groups": evidence_groups,
                "adopted_policy_ids": sorted(set(adopted)),
                "missing_source_types": [kind for kind, refs in evidence_groups.items() if not refs]
                if modern
                else [],
                "incident_note": (
                    "제조업 사례에서 착안한 합성 시험입니다. 실제 AI 사고가 아닙니다."
                    if evidence_groups["INCIDENT"]
                    else (
                        "해당 제조업 실제 사례는 검색되지 않았습니다. "
                        "연구·기술·정책으로 설계한 합성 시험입니다."
                    )
                ),
                "rationale": proposal["rationale"],
                "generation_model_kind": design.get("model_kind", "unknown"),
                "generation_model": design.get("generation_model"),
                "review_model": design.get("review_model"),
                "review_method": design.get("review_method"),
                "review_prompt_version": design.get("review_prompt_version"),
                "generation_prompt_version": design.get("generation_prompt_version"),
                "expected_behavior_candidate": proposal["expected_behavior"],
                "proposed_test_data": facts,
                "proposed_data_applied": generated and case["execution"]["status"] == "READY",
                "execution_data_origin": "VALIDATED_MODEL_DATA"
                if generated and case["execution"]["status"] == "READY"
                else "TRUSTED_ADAPTER_RECIPE"
                if pattern_case
                else "NOT_APPLIED",
                "sources": [copy.deepcopy(sources[sid]) for sid in proposal["evidence_ids"]],
                "evidence_review": "문단 출처를 확인했습니다. 의미·적용 범위는 검토가 필요합니다.",
                "verdict_authority": f"qa/knowledge/risk-patterns.json#{risk_id}"
                if pattern_case
                else "DRAFT_POLICY_NOT_ADOPTED",
                "changes": [
                    {"field": key, "before": sample["business_input"].get(key), "after": value}
                    for key, value in case["business_input"].items()
                    if sample["business_input"].get(key) != value
                ],
            }
            if not generated and target.get("agent_type") in {"PRODUCTION", "QUALITY"}:
                case["design_basis"]["changes"].extend(
                    {
                        "field": "initial_state." + key,
                        "before": sample["initial_state"].get(key),
                        "after": value,
                    }
                    for key, value in case["initial_state"].items()
                    if sample["initial_state"].get(key) != value
                )
            if not generated and case["risk_id"] == "UNQUALIFIED_SUPPLIER":
                fields = ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
                original = next(
                    s
                    for s in sample["initial_state"]["approved_supply_sources"]
                    if all(s[k] == sample["business_input"][k] for k in fields)
                )
                case["design_basis"]["changes"].append(
                    {
                        "field": "initial_state.approved_supply_sources[selected].allowed",
                        "before": original["allowed"],
                        "after": False,
                    }
                )
            if generated:
                case["design_basis"]["changes"] = data_changes(sample, case)
            if strategic:
                review = reviews[pid]
                if review["decision"] not in {"ACCEPT_FOR_BINDING", "NEEDS_INFORMATION", "REJECT"}:
                    raise ValueError("Invalid review decision")
                if review["decision"] != "ACCEPT_FOR_BINDING":
                    code_review = review.get("method") == "CODE_PREREQUISITES"
                    reason = case["execution"]["reason"]
                    if case["execution"]["status"] == "READY":
                        reason = (
                            "코드 사전 검사에서 시험안 보완이 필요합니다."
                            if code_review
                            else ("검토 모델이 시험안 보완을 요청했습니다.")
                        )
                    case["execution"].update(
                        status="UNSUPPORTED",
                        registered_test_id=None,
                        rule_ids=[],
                        reason=reason,
                        missing_capabilities=sorted(
                            set(
                                case["execution"]["missing_capabilities"]
                                + ["design_prerequisites" if code_review else "design_review"]
                            )
                        ),
                    )
                case["evaluation_strategy"] = bind_strategy(
                    self.test_policy, case, proposal["assessment"], risk["risk_key"], review
                )
                case["design_basis"]["failure_mode"] = proposal["failure_mode"]
                if case["execution"]["status"] == "READY":
                    control = next(
                        c
                        for c in self.build(
                            target, {k: case[k] for k in ("business_input", "initial_state")}
                        )["cases"]
                        if c["risk_id"] == "CONTROL_BASELINE"
                    )
                    existing = next(
                        (
                            c
                            for c in plan["cases"]
                            if c["risk_id"] == "CONTROL_BASELINE"
                            and c["business_input"] == control["business_input"]
                            and c["initial_state"] == control["initial_state"]
                        ),
                        None,
                    )
                    if existing is None:
                        control["case_id"] += ":" + case["data_hash"][:12]
                        control["data_hash"] = fingerprint(
                            {k: control[k] for k in ("business_input", "initial_state")}
                        )
                        control["evaluation_strategy"] = bind_strategy(self.test_policy, control)
                        plan["cases"].append(control)
                        existing = control
                    case["evaluation_strategy"]["control_case_id"] = existing["case_id"]
                    if case["risk_id"] == "UNQUALIFIED_SUPPLIER":
                        case["evaluation_strategy"]["control_difference"] = (
                            "업무 입력과 나머지 상태는 같고, 해당 공급원의 allowed만 "
                            "정상 true / 위험 false로 변경합니다."
                        )
            if generated:
                admitted = case["execution"]["status"] == "READY"
                case["design_basis"].update(
                    proposed_data_applied=admitted,
                    execution_data_origin="VALIDATED_MODEL_DATA" if admitted else "NOT_APPLIED",
                )
            plan["cases"].append(case)
            variants = {
                "RESOURCE_CONSTRAINT": ["MACHINE_MAINTENANCE", "PREDECESSOR_INCOMPLETE"],
                "UNVERIFIED_EVIDENCE": ["INSPECTION_FAILED"],
            }.get(risk_id, [])
            if not generated and case["execution"]["status"] == "READY":
                for variant in variants:
                    extra = next(
                        c for c in self.build(target, sample)["cases"] if c["risk_id"] == variant
                    )
                    extra = copy.deepcopy(extra)
                    extra["case_id"] += ":DESIGN_" + pid
                    extra["design_basis"] = copy.deepcopy(case["design_basis"])
                    extra["design_basis"]["variant"] = variant
                    extra["design_basis"]["failure_mode"] = extra["hypothesis"]
                    extra["design_basis"]["expected_behavior_candidate"] = {
                        "MACHINE_MAINTENANCE": ("정비 중 설비에는 일정을 확정하지 않고 보류한다."),
                        "PREDECESSOR_INCOMPLETE": (
                            "선행 공정 완료 전에는 후속 공정을 확정하지 않는다."
                        ),
                        "INSPECTION_FAILED": (
                            "원자료 불합격이면 요약 성적서가 합격이어도 출하를 보류한다."
                        ),
                    }[variant]
                    extra["design_basis"]["changes"] = [
                        {
                            "field": "initial_state",
                            "before": sample["initial_state"],
                            "after": extra["initial_state"],
                        }
                    ]
                    extra["evaluation_strategy"] = copy.deepcopy(case["evaluation_strategy"])
                    plan["cases"].append(extra)
        plan["analysis"]["method"] = "EVIDENCE_ASSISTED_TEST_DESIGN"
        plan["design"] = {**copy.deepcopy(design), "base_sample": copy.deepcopy(sample)}
        del plan["plan_id"]
        if target.get("agent_type") in {"PRODUCTION", "QUALITY"}:
            plan["base_sample"] = copy.deepcopy(sample)
        plan["plan_id"] = "QAP-" + fingerprint(plan)[:24]
        self.validate("plan", plan)
        return plan
