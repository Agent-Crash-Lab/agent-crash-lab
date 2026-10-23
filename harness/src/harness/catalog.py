"""Test catalog assembled from config, scenarios and fixtures (HARNESS_SPEC 1.2, 2.3, 3.6)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from harness.adapters.manufacturing import CONDITIONS, RULES
from harness.planning import QaPlanner

# Titles for agent unit tests follow docs/evaluation.md; the scenario files carry none.
PURCHASE_TESTS = {
    "PA01": ("정상 응답·승인", "purchase-normal", "APPROVED"),
    "PA02": ("승인 거절", "purchase-normal", "REJECTED"),
    "PA03": ("첫 응답 timeout·후속 응답", "purchase-timeout-once", "APPROVED"),
}
INVESTIGATION_TITLES = {
    "IA01": "중복 발주·응답 차단·재시도 사건",
    "IA02": "업무 상태 조회 실패·로그 누락 사건",
    "IA03": "무승인 호출 시도·서버 차단 사건",
}


@dataclass(frozen=True)
class TestSpec:
    test_id: str
    test_kind: str  # SYSTEM | PURCHASE_AGENT | INVESTIGATION_AGENT
    title: str
    version: str
    expected_approval: str | None = None
    rule_ids: list[str] = field(default_factory=list)
    agent_fixture_id: str | None = None
    fixture_decision: str | None = None
    target_run_id: str | None = None


class Catalog:
    def __init__(self, root: Path):
        self.root = root
        self.planner = QaPlanner(root)
        self.config = self.planner.config
        refs = self.config["references"]
        purchase = self._json(refs["target_profiles"])["agents"]["PURCHASE"]
        self.seed = {
            "fixture_id": purchase["fixture_id"],
            "seed": purchase["sample_data"]["initial_state"],
        }
        self.cases = {
            case["test_id"]: case for case in self._json(refs["investigation_cases"])["cases"]
        }
        scenarios = self._json(refs["scenarios"])
        self.rules = {rule["rule_id"]: rule for rule in scenarios["base_rules"]}
        self.event_schema = self._json(refs["event_schema"])
        self.qa_plan = self.planner.build()
        self.harness_rules = {
            rule_id for rule_id, rule in self.rules.items() if rule.get("judged_by") == "harness"
        }
        self.tests: dict[str, TestSpec] = {}

        enabled = set(self.config["enabled_scenarios"])
        for scenario in scenarios["base_scenarios"]:
            if scenario["scenario_id"] not in enabled:
                continue
            runner_only = scenario["test_runner_only"]
            self.tests[scenario["scenario_id"]] = TestSpec(
                test_id=scenario["scenario_id"],
                test_kind="SYSTEM",
                title=scenario["title"],
                version=scenario["version"],
                expected_approval=_expected_approval(runner_only["interventions"]),
                rule_ids=list(runner_only["oracle_rule_ids"]),
            )
        for conditions in CONDITIONS.values():
            for risk, (test_id, title) in conditions.items():
                self.tests[test_id] = TestSpec(
                    test_id,
                    "SYSTEM",
                    title,
                    "0.1.0",
                    expected_approval="REJECTED" if risk == "APPROVAL_DENIED" else None,
                    rule_ids=list(RULES),
                )
        self.rules.update({key: {"name": name} for key, (name, _) in RULES.items()})
        for test_id, (title, fixture_id, decision) in PURCHASE_TESTS.items():
            self.tests[test_id] = TestSpec(
                test_id=test_id,
                test_kind="PURCHASE_AGENT",
                title=title,
                version="0.1.0",
                expected_approval=decision,
                agent_fixture_id=fixture_id,
                fixture_decision=decision,
                rule_ids=sorted(self.harness_rules),
            )
        for test_id, title in INVESTIGATION_TITLES.items():
            case = self.cases[test_id]
            self.tests[test_id] = TestSpec(
                test_id=test_id,
                test_kind="INVESTIGATION_AGENT",
                title=title,
                version="0.1.0",
                agent_fixture_id=case["fixture_id"],
                rule_ids=sorted(self.harness_rules),
                target_run_id=case["run_id"],
            )

    def _json(self, path):
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    @property
    def systems(self) -> dict[str, dict]:
        return self.config["systems"]

    @property
    def seed_request(self) -> dict:
        return dict(self.seed["seed"]["request"])

    def rule_scopes(self, rule_id: str) -> list[str]:
        return (
            RULES[rule_id][1]
            if rule_id in RULES
            else list(self.config["evaluation"]["rule_check_scopes"].get(rule_id, []))
        )

    def scenarios_response(self) -> dict:
        return {
            "systems": [
                {"system_id": system_id, "server_policy_version": value["server_policy_version"]}
                for system_id, value in self.systems.items()
            ],
            "tests": [
                {
                    "test_id": test.test_id,
                    "test_kind": test.test_kind,
                    "title": test.title,
                    **(
                        {"expected_approval": test.expected_approval}
                        if test.test_kind == "SYSTEM"
                        else {}
                    ),
                    "rules": [
                        {
                            "rule_id": rule_id,
                            "name": self.rules[rule_id]["name"],
                            "scopes": self.rule_scopes(rule_id),
                        }
                        for rule_id in test.rule_ids
                    ],
                }
                for test in self.tests.values()
            ],
        }

    def manifest(self, test: TestSpec, system_id: str | None, plan=None, case=None) -> dict:
        execution = self.config["execution"]
        system = self.systems[system_id] if system_id else None
        faults = []
        system_test = test.test_kind == "SYSTEM"
        plan = plan or self.qa_plan
        case = case or (self.planned_case(test.test_id) if system_test else None)
        if case and case["simulation"]["fault"]:
            faults.append({"fault_id": "FLT-001", **case["simulation"]["fault"]})
        return {
            "qa_plan_id": plan["plan_id"] if system_test else None,
            "qa_case_id": case["case_id"] if case else None,
            "target_id": plan["target_id"] if system_test else None,
            "target_hash": plan["target_hash"] if system_test else None,
            "data_hash": case.get("data_hash", plan["data_hash"]) if case else None,
            "registered_target": plan.get("design", {}).get("registration")
            if system_test
            else None,
            "test_id": test.test_id,
            "test_version": test.version,
            "system_id": system_id,
            "server_policy_version": system["server_policy_version"] if system else None,
            "fixture_id": self.seed["fixture_id"] if system_test else None,
            "agent_mode": "mcp" if system_test else "mock",
            "agent_fixture_id": None if system_test else test.agent_fixture_id,
            "faults": faults if system_test else [],
            # Agent exposes no version yet (HARNESS_SPEC §7 #1).
            "agent_version": None,
            "prompt_version": None,
            "model_kind": None,
            "model": None,
            "mcp_version": None,
            "limits": {
                "max_agent_turns": execution["max_agent_turns"],
                "max_tool_calls": execution["max_tool_calls"],
                "max_active_seconds_per_agent": execution["max_active_seconds_per_agent"],
                "tool_timeout_seconds": execution["tool_timeout_seconds"],
                "max_total_run_seconds": execution["max_total_run_seconds"],
                "approval_wait_timeout_seconds": self.config["approval"]["wait_timeout_seconds"],
            },
            "retry_policy": {
                key: execution[key]
                for key in (
                    "write_retries_after_ambiguous_error",
                    "read_retries_after_transient_error",
                    "preserve_request_id_on_retry",
                    "preserve_payload_on_retry",
                )
            },
            "rule_version": self.config["evaluation"]["rule_version"],
            "config_version": self.config["config_version"],
        }

    def planned_case(self, test_id):
        return next(
            (
                case
                for case in self.qa_plan["cases"]
                if case["execution"]["registered_test_id"] == test_id
                and case["execution"]["status"] == "READY"
            ),
            None,
        )


def _expected_approval(interventions) -> str | None:
    for item in interventions:
        if item["stage"] == "approval":
            if item["action"].startswith("approve"):
                return "APPROVED"
            if item["action"].startswith("reject"):
                return "REJECTED"
    return None
