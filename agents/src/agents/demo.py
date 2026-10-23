"""Offline CLI examples for the same runtime used by the HTTP API."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.config import Settings
from agents.models import PurchaseRequest, ResumeRequest, StartRequest
from agents.runtime import Runtime


async def wait(runtime, run_id):
    while runtime.status(run_id)["status"] in {"PREPARING", "RUNNING"}:
        await asyncio.sleep(0.01)
    return runtime.status(run_id)


async def demo(scenario):
    settings = Settings(agent_model_mode="offline")
    with TemporaryDirectory() as temporary:
        settings.agent_state_dir = Path(temporary)
        runtime = await Runtime(settings).open()
        try:
            if scenario.startswith("ia"):
                body = StartRequest(
                    run_id="demo-investigation",
                    agent_kind="INVESTIGATION_AGENT",
                    target_run_id="demo-target",
                    fixture_id=scenario + "-v1",
                )
            else:
                seed = json.loads(
                    (
                        settings.agent_project_root / "qa/examples/targets/agents.json"
                    ).read_text()
                )
                profile = seed["agents"]["PURCHASE"]
                request = PurchaseRequest.model_validate(profile["sample_data"]["business_input"])
                fixture = (
                    "purchase-" + scenario if scenario.startswith("timeout") else "purchase-normal"
                )
                body = StartRequest(run_id="demo-purchase", request=request, fixture_id=fixture)
            await runtime.start(body)
            run = await wait(runtime, body.run_id)
            if run["status"] == "WAITING_APPROVAL":
                print(json.dumps(run, ensure_ascii=False, indent=2))
                await runtime.resume(
                    body.run_id,
                    ResumeRequest(
                        request_id=body.request.request_id,
                        approval_id="AP-MOCK",
                        decision="REJECTED" if scenario == "rejected" else "APPROVED",
                        payload_hash=body.request.payload_hash(),
                        approver_id="mock-approver",
                        decided_at=datetime.now(UTC),
                    ),
                )
                run = await wait(runtime, body.run_id)
            print(json.dumps(run, ensure_ascii=False, indent=2))
            if run["status"] == "ERROR":
                raise SystemExit(1)
        finally:
            await runtime.close()


def main():
    parser = argparse.ArgumentParser(description="Mock data only; no business writes or LLM calls")
    parser.add_argument(
        "--scenario",
        default="approved",
        choices=[
            "approved",
            "rejected",
            "timeout-once",
            "timeout-always",
            "ia01",
            "ia02",
            "ia03",
        ],
    )
    asyncio.run(demo(parser.parse_args().scenario))


if __name__ == "__main__":
    main()
