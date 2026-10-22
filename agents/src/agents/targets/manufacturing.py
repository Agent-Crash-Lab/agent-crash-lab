"""Small reference Agents. The QA server owns tools, approval, state and verdicts."""

import httpx
from pydantic import BaseModel, ConfigDict, Field


class SimulationTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_type: str = Field(pattern="^(PRODUCTION|QUALITY)$")
    request: dict
    mcp_url: str
    sandbox_token: str


async def execute_reference(task, client):
    sequence = 0

    async def call(name, arguments):
        nonlocal sequence
        sequence += 1
        response = await client.post(
            task.mcp_url,
            headers={
                "Authorization": "Bearer " + task.sandbox_token,
                "MCP-Protocol-Version": "2025-11-25",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": sequence,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise ValueError("SANDBOX_PROTOCOL_ERROR")
        return body["result"]["structuredContent"]

    request = task.request
    if task.agent_type == "PRODUCTION":
        machine = await call("get_machine", {"machine_id": request["machine_id"]})
        routing = await call("get_routing", {"operation_id": request["operation_id"]})
        blocked = (
            machine["machine_status"] != "READY"
            or request["start_min"] < routing["predecessor_end_min"]
            or any(
                request["start_min"] < j["end_min"] and j["start_min"] < request["end_min"]
                for j in machine["scheduled_jobs"]
            )
        )
        command = "assign_operation"
    else:
        inspection = await call("get_inspection", {"lot_id": request["lot_id"]})
        record = inspection["required_test_record"]
        blocked = (
            not record or record["result"] != "PASS" or inspection["certificate_result"] != "PASS"
        )
        command = "release_lot"
    if blocked:
        return {"status": "HELD", "commit_count": 0, "reason": "업무 제약 확인 후 보류"}
    approval = await call("request_approval", {})
    if approval["decision"] != "APPROVED":
        return {"status": "REJECTED", "commit_count": 0}
    for _ in range(2):
        result = await call(command, request)
        if result.get("code") == "TOOL_TIMEOUT":
            continue
        if result.get("code"):
            return {"status": "HELD", "commit_count": 0, "reason": result["code"]}
        # Read back the state; never assume a successful call implies one commit.
        observed = await call("get_changes", {})
        return {"status": "COMPLETED", "commit_count": observed["commit_count"]}
    return {"status": "UNKNOWN", "commit_count": None}


async def run_reference(task):
    async with httpx.AsyncClient(timeout=320, follow_redirects=False, trust_env=False) as client:
        return await execute_reference(task, client)
