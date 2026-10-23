import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from agents.config import Settings
from agents.models import PurchaseRequest, ResumeRequest, StartRequest
from agents.runtime import Runtime

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-internal-token-not-a-real-secret"


@pytest.fixture(autouse=True)
def offline_test_environment(monkeypatch):
    # A developer's exported live settings must never make the ordinary suite billable.
    monkeypatch.setenv("AGENT_MODEL_MODE", "offline")
    monkeypatch.setenv("QA_DESIGN_MODEL_MODE", "offline")
    monkeypatch.setenv("QA_DESIGN_LLM_MODEL", "")
    monkeypatch.setenv("QA_REVIEW_LLM_MODEL", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("PURCHASE_LLM_MODEL", "")
    monkeypatch.setenv("INVESTIGATION_LLM_MODEL", "")
    monkeypatch.setenv("LLM_BUDGET_STAGE", "smoke")
    monkeypatch.delenv("LLM_BUDGET_PATH", raising=False)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, agent_project_root=ROOT, agent_state_dir=tmp_path, internal_api_token=TOKEN
    )


@pytest_asyncio.fixture
async def runtime(settings):
    service = await Runtime(settings).open()
    yield service
    await service.close()


def purchase(run_id="RUN-TEST", fixture_id="purchase-normal", **changes):
    data = json.loads((ROOT / "qa/examples/targets/agents.json").read_text())["agents"][
        "PURCHASE"
    ]["sample_data"]["business_input"]
    return StartRequest(
        run_id=run_id, fixture_id=fixture_id, request=PurchaseRequest(**{**data, **changes})
    )


def approval(body, decision="APPROVED", **changes):
    return ResumeRequest(
        **{
            "request_id": body.request.request_id,
            "approval_id": "AP-TEST",
            "decision": decision,
            "payload_hash": body.request.payload_hash(),
            "approver_id": "test-approver",
            "decided_at": datetime(2026, 10, 19, tzinfo=UTC),
            **changes,
        }
    )


async def settled(runtime, run_id):
    for _ in range(300):
        run = runtime.status(run_id)
        if run["status"] not in {"PREPARING", "RUNNING"} and not runtime.tasks:
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("Run did not settle")
