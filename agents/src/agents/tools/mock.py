"""Scripted fixture responses, not a simulated business database or Oracle."""

import json
from copy import deepcopy

from agents.tools.errors import ToolError


class MockTools:
    def __init__(self, root, fixture_id, target_run_id=None):
        self.root, self.fixture_id, self.target_run_id = root, fixture_id, target_run_id
        self.create_count = 0
        self.calls = []

    def investigation_evidence(self):
        cases = json.loads((self.root / "qa/examples/investigation-cases.json").read_text())[
            "cases"
        ]
        case = next(item for item in cases if item["fixture_id"] == self.fixture_id)

        def scope(value):
            if isinstance(value, dict):
                return {key: scope(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scope(item) for item in value]
            return self.target_run_id if value == case["run_id"] else value

        # Never pass expected_facts/cause_hypothesis/review to the Agent or model.
        return scope(deepcopy(case["evidence"]))

    async def call(self, name, arguments):
        self.calls.append({"tool": name, "arguments": deepcopy(arguments)})
        if name == "get_supplier_eligibility":
            seed = json.loads((self.root / "qa/examples/purchase-initial-state.json").read_text())[
                "seed"
            ]
            source = next(
                (
                    s
                    for s in seed["approved_supply_sources"]
                    if all(
                        s[k] == arguments[k]
                        for k in ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
                    )
                ),
                None,
            )
            return {
                **arguments,
                "policy_found": source is not None,
                "allowed": bool(source and source["allowed"]),
                "policy_version": source["policy_version"] if source else 0,
            }
        if name in {"get_inventory", "get_supplier"}:
            seed = json.loads((self.root / "qa/examples/purchase-initial-state.json").read_text())[
                "seed"
            ]
            if name == "get_inventory":
                part = next(
                    (
                        part
                        for part in seed["parts"]
                        if part["part_id"] == arguments["part_id"]
                        and part["plant_id"] == arguments["plant_id"]
                    ),
                    None,
                )
                if part is None:
                    raise ToolError("VALIDATION_ERROR")
                return {
                    "part_id": part["part_id"],
                    "plant_id": part["plant_id"],
                    "available_quantity": part["inventory"],
                    "unit": part["unit"],
                    "inventory_version": 1,
                }
            supplier = next(
                (
                    supplier
                    for supplier in seed["suppliers"]
                    if supplier["supplier_id"] == arguments["supplier_id"]
                ),
                None,
            )
            if supplier is None:
                raise ToolError("VALIDATION_ERROR")
            return {**supplier, "supplier_version": 1}
        if name == "create_purchase_order":
            self.create_count += 1
            if self.fixture_id == "purchase-timeout-always" or (
                self.fixture_id == "purchase-timeout-once" and self.create_count == 1
            ):
                raise ToolError("TOOL_TIMEOUT", retryable=True)
            request = arguments["request"]
            return {
                "request_id": request["request_id"],
                "order_id": "PO-MOCK-001",
                "status": "CREATED",
                "committed_version": request["request_version"],
            }
        if name == "get_order_by_request":
            return {"request_id": arguments["request_id"], "orders": []}
        evidence = self.investigation_evidence()
        if name == "get_failed_checks":
            code = {"ia01-v1": "R03", "ia02-v1": "R09", "ia03-v1": "R05"}[self.fixture_id]
            return {
                "run_id": self.target_run_id,
                "checks": [
                    {
                        "run_id": self.target_run_id,
                        "check_id": "CHK-MOCK",
                        "rule_id": code,
                        "rule_version": "0.1.0",
                        "scope": {
                            "R03": "business_state",
                            "R09": "qa_evidence",
                            "R05": "agent_behavior",
                        }[code],
                        "verdict": "INCONCLUSIVE" if self.fixture_id == "ia02-v1" else "FAIL",
                        "reason": "합성 사건의 조사 입력",
                        "evidence_ids": [],
                    }
                ],
            }
        if name == "get_business_state":
            snapshot = next(
                (item for item in evidence if item["kind"] == "BUSINESS_SNAPSHOT"), None
            )
            if snapshot is None:
                raise ToolError("INTERNAL_ERROR", retryable=True)
            return {
                "run_id": self.target_run_id,
                "request_id": "REQ-001",
                "snapshot_complete": True,
                "pending_tool_calls": 0,
                "snapshot_evidence_ids": [snapshot["evidence_id"]],
                "commit_evidence_ids": [],
                **snapshot["payload"],
            }
        if name == "get_run_trace":
            trace = next((item for item in evidence if item["kind"] == "RUN_TRACE"), None)
            blocked = next((item for item in evidence if item["kind"] == "BLOCKED_TOOL_CALL"), None)
            events = trace["payload"]["events"] if trace else []
            if blocked:
                events = [
                    {
                        "run_id": self.target_run_id,
                        "event_id": "EV-MOCK-BLOCKED",
                        "event_type": "TOOL_RESPONDED",
                        "evidence_ids": [blocked["evidence_id"]],
                        "payload": blocked["payload"],
                    }
                ]
            return {"run_id": self.target_run_id, "events": events, "tool_calls": []}
        if name == "search_failure_guides":
            document = next(
                item for item in self.guides() if item["document_id"] == "investigation-guide"
            )
            return {
                "results": [
                    {
                        "document_id": document["document_id"],
                        "version": document["version"],
                        "title": document["title"],
                        "location": "전체",
                        "snippet": "사실과 추정을 구분한다",
                        "resource_uri": f"guide://{document['document_id']}/{document['version']}",
                    }
                ]
            }
        raise ToolError("PERMISSION_DENIED")

    def guides(self):
        return json.loads((self.root / "qa/knowledge/guides/index.json").read_text())["documents"]

    async def resource(self, uri):
        for guide in self.guides():
            if uri == f"guide://{guide['document_id']}/{guide['version']}":
                return (self.root / "qa/knowledge/guides" / guide["body_path"]).read_text()
        raise ToolError("PERMISSION_DENIED")
