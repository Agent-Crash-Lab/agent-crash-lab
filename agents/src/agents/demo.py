"""Run a mock purchase flow: uv run --locked python -m agents.demo."""

import argparse
import json

from agents.graph.purchase import PurchaseAgent
from agents.models import ApprovalDecision, PurchaseRequest
from agents.tools.mock import MockBusinessTools


def main() -> None:
    parser = argparse.ArgumentParser(description="Local mock demo; no actual order is created")
    parser.add_argument(
        "--scenario",
        choices=["approved", "rejected", "timeout-once", "timeout-always"],
        default="approved",
    )
    args = parser.parse_args()
    responses = []
    if args.scenario in {"timeout-once", "timeout-always"}:
        responses.append(TimeoutError("mock timeout"))
    if args.scenario == "timeout-always":
        responses.append(TimeoutError("mock timeout"))
    agent = PurchaseAgent(MockBusinessTools(responses=responses))
    request = PurchaseRequest(
        run_id="demo-run",
        request_id="demo-request",
        part_id="PART-A",
        supplier_id="SUP-01",
        quantity=100,
    )
    print(json.dumps(agent.start(request), ensure_ascii=False, indent=2))
    decision = ApprovalDecision(
        request_id=request.request_id,
        decision="REJECTED" if args.scenario == "rejected" else "APPROVED",
        approval_id=None if args.scenario == "rejected" else "mock-approval",
    )
    print(json.dumps(agent.resume(request.run_id, decision), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
