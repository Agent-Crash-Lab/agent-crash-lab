import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from harness import oracle
from harness.api import create_app
from harness.clients import ClientError
from harness.config import Settings

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-internal-token-not-a-real-secret"
GATEWAY = {"X-Internal-Token": TOKEN, "X-User-Id": "requester-01", "X-User-Roles": "REQUESTER"}


def payload_hash(request: dict) -> str:
    encoded = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class FakeMcp:
    """Stands in for mcp-server's /internal/sandbox/** (MCP_SPEC §3)."""

    def __init__(self):
        self.calls = []
        self.request = json.loads((ROOT / "qa/examples/purchase-initial-state.json").read_text())[
            "seed"
        ]["request"]
        self.orders = 1
        self.fault_status = "APPLIED"

    async def initialize(self, body):
        self.calls.append(("initialize", body))
        if body.get("initial_state"):
            self.request = body["initial_state"]["request"]
        return {
            "run_id": body["run_id"],
            "server_policy_version": body["server_policy_version"],
            "mcp_url": "http://mcp-server:8081/mcp",
            "agent_tokens": {"purchase_agent": "PA-TOKEN", "investigation_agent": "IA-TOKEN"},
            "request": dict(self.request),
        }

    async def request_approval(self, run_id, request):
        self.calls.append(("request_approval", run_id))
        return {
            "approval_request_id": "APR-001",
            "request_id": request["request_id"],
            "payload_hash": payload_hash(request),
            "requested_at": "2026-10-20T00:00:00Z",
            "expires_at": "2026-10-20T00:05:00Z",
        }

    async def faults(self, run_id):
        self.calls.append(("faults", run_id))
        return [{"fault_id": "FLT-001", "status": self.fault_status, "applied_count": 1}]

    async def finalize(self, run_id, wait_ms):
        self.calls.append(("finalize", run_id))
        return {
            "run_id": run_id,
            "request_id": self.request["request_id"],
            "snapshot_complete": True,
            "pending_tool_calls": 0,
            "snapshot_evidence_ids": ["EV-SNAPSHOT-001"],
            "commit_evidence_ids": [f"EV-COMMIT-00{i + 1}" for i in range(self.orders)],
            "orders": [{"order_id": f"PO-00{i + 1}"} for i in range(self.orders)],
            "approvals": [],
        }

    def names(self):
        return [name for name, _ in self.calls]


class FakeAgent:
    """Mimics agents/ internal API states and events (HARNESS_SPEC §3)."""

    def __init__(self):
        self.runs, self.log, self.resumes = {}, {}, []
        self.report_evidence = None  # investigation facts evidence override
        self.expire_approval = False
        self.fail_resume = 0  # fail this many resume calls first

    def _event(self, run_id, event_type, payload=None):
        log = self.log.setdefault(run_id, [])
        kind = self.runs[run_id]["agent_kind"]
        log.append(
            {
                "run_id": run_id,
                "event_id": str(uuid4()),
                "sequence": len(log) + 1,
                "event_type": event_type,
                "producer": "agents",
                "actor_id": "investigation_agent"
                if kind == "INVESTIGATION_AGENT"
                else "purchase_agent",
                "node_id": "investigator" if kind == "INVESTIGATION_AGENT" else "agent",
                "parent_event_id": log[-1]["event_id"] if log else None,
                "tool_call_id": None,
                "evidence_ids": [],
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": payload or {},
            }
        )

    def _tool(self, run_id, tool, arguments, status="OK", code=None):
        call_id = str(uuid4())
        self._event(
            run_id,
            "AGENT_TOOL_CALLED",
            {"agent_call_id": call_id, "tool": tool, "arguments": arguments},
        )
        payload = {"agent_call_id": call_id, "status": status}
        if code:
            payload["code"] = code
        self._event(run_id, "AGENT_TOOL_RESPONDED", payload)

    def _finish(self, run_id, status="COMPLETED", result=None, reason=None):
        run = self.runs[run_id]
        run.update(status=status, result=result, reason=reason, finished_at=time.time())
        self._event(
            run_id, "RUN_FINISHED", {"status": status, **({"reason": reason} if reason else {})}
        )

    async def start(self, body):
        if body["run_id"] in self.runs:
            raise ClientError("agents", 409, "RUN_EXISTS")
        run = {
            **body,
            "status": "PREPARING",
            "created_at": time.time(),
            "finished_at": None,
            "turns": 1,
            "tool_calls": 0,
            "active_seconds": 0.1,
            "result": None,
            "model_kind": "fixture"
            if body["agent_kind"] == "INVESTIGATION_AGENT"
            else "deterministic",
        }
        run.pop("agent_token", None)
        self.runs[body["run_id"]] = run
        self._event(body["run_id"], "RUN_STARTED", {"mode": body["mode"]})
        if body["agent_kind"] == "PURCHASE_AGENT":
            request = body["request"]
            self._tool(
                body["run_id"],
                "get_inventory",
                {"part_id": request["part_id"], "plant_id": request["plant_id"]},
            )
            self._tool(body["run_id"], "get_supplier", {"supplier_id": request["supplier_id"]})
            if self.expire_approval:
                self._finish(body["run_id"], "ERROR", reason="APPROVAL_WAIT_EXPIRED")
            else:
                run.update(status="WAITING_APPROVAL", payload_hash=payload_hash(request))
                self._event(
                    body["run_id"], "AGENT_WAITING_APPROVAL", {"payload_hash": run["payload_hash"]}
                )
        else:
            self._investigate(body)
        return dict(run)

    def _investigate(self, body):
        run_id, target = body["run_id"], body["target_run_id"]
        for tool in (
            "get_failed_checks",
            "get_run_trace",
            "get_business_state",
            "search_failure_guides",
        ):
            self._tool(
                run_id,
                tool,
                {"run_id": target} if tool != "search_failure_guides" else {"query": "q"},
            )
        evidence = self.report_evidence or (
            ["IA01-STATE"] if body["mode"] == "mock" else ["EV-SNAPSHOT-001"]
        )
        self._event(run_id, "REPORT_READY")
        self._finish(
            run_id,
            result={
                "target_run_id": target,
                "facts": [{"text": "조회된 발주는 2건입니다.", "evidence_ids": evidence}],
                "cause_candidates": [],
                "missing_evidence": [],
                "improvements": [],
                "retest_scenario_ids": ["S03"],
            },
        )

    async def status(self, run_id):
        if run_id not in self.runs:
            raise ClientError("agents", 404, "RUN_NOT_FOUND")
        return dict(self.runs[run_id])

    async def resume(self, run_id, body):
        run = self.runs[run_id]
        if self.fail_resume:
            self.fail_resume -= 1
            raise ClientError("agents", None, "TRANSPORT_ERROR")
        if run["status"] != "WAITING_APPROVAL":
            raise ClientError("agents", 409, "NOT_WAITING_APPROVAL")
        self.resumes.append((run_id, body))
        run["status"] = "RUNNING"
        self._event(run_id, "AGENT_APPROVAL_RECEIVED", {"decision": body["decision"]})
        request = run["request"]
        if body["decision"] == "REJECTED":
            self._finish(
                run_id,
                result={
                    "request_id": request["request_id"],
                    "outcome": "REJECTED",
                    "order_id": None,
                    "message": "거절",
                },
            )
            return dict(run)
        arguments = {"request": request, "approval_id": body["approval_id"]}
        if run.get("fixture_id") == "purchase-timeout-once":
            self._tool(run_id, "create_purchase_order", arguments, "ERROR", "TOOL_TIMEOUT")
        self._tool(run_id, "create_purchase_order", arguments)
        self._finish(
            run_id,
            result={
                "request_id": request["request_id"],
                "outcome": "SUCCEEDED",
                "order_id": "PO-001",
                "message": "완료",
            },
        )
        return dict(run)

    async def events(self, run_id, after_sequence):
        return [e for e in self.log.get(run_id, []) if e["sequence"] > after_sequence][:100]


@pytest.fixture(autouse=True)
def no_business_db(monkeypatch):
    """Runner tests have no business DB; the Oracle itself is tested in test_oracle.py."""
    monkeypatch.setattr(oracle, "evaluate", lambda ctx: [])


@pytest.fixture
def fakes():
    return FakeMcp(), FakeAgent()


@pytest.fixture
def client(tmp_path, fakes):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/harness.sqlite",
        internal_api_token=TOKEN,
        harness_dev_auth=True,
        harness_project_root=ROOT,
        poll_interval_seconds=0.01,
        finalize_wait_ms=0,
        sse_keepalive_seconds=0.05,
        events_hold_seconds=0.05,
    )
    mcp, agent = fakes
    with TestClient(create_app(settings, mcp=mcp, agents=agent)) as test_client:
        yield test_client


def wait_for(client, run_id, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if predicate(run):
            # Let buffered events (events_hold_seconds) reach the store.
            time.sleep(0.2)
            return client.get(f"/api/runs/{run_id}").json()
        time.sleep(0.02)
    raise AssertionError(f"timeout: {client.get(f'/api/runs/{run_id}').json()}")


def done(run):
    return run["status"] in {"COMPLETED", "ERROR"} and run["investigation"]["status"] != "RUNNING"
