"""HTTP clients for mcp-server (MCP_SPEC §3) and the Agent service (HARNESS_SPEC §3)."""

import httpx


class ClientError(Exception):
    def __init__(self, service: str, status: int | None, code: str):
        super().__init__(f"{service} {status} {code}")
        self.service, self.status, self.code = service, status, code


def _code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "UNKNOWN"
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):  # mcp-server
            return str(body["error"].get("code", "UNKNOWN"))
        if isinstance(body.get("detail"), str):  # agents
            return body["detail"]
        if "detail" in body:
            return "VALIDATION_ERROR"
    return "UNKNOWN"


class _Http:
    service = ""

    def __init__(self, base_url: str, token: str, timeout: float = 10):
        self.http = httpx.AsyncClient(
            base_url=base_url, headers={"X-Internal-Token": token}, timeout=timeout
        )

    async def close(self):
        await self.http.aclose()

    async def _send(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ClientError(self.service, None, "TRANSPORT_ERROR") from exc
        if response.status_code >= 400:
            raise ClientError(self.service, response.status_code, _code(response))
        return response.json() if response.content else {}


class McpClient(_Http):
    service = "mcp-server"

    async def search_knowledge(self, body: dict) -> dict:
        return await self._send("POST", "/internal/knowledge/search", json=body)

    async def initialize(self, body: dict) -> dict:
        return await self._send("POST", "/internal/sandbox/runs", json=body)

    async def request_approval(self, run_id: str, request: dict) -> dict:
        return await self._send(
            "POST", f"/internal/sandbox/runs/{run_id}/approval-requests", json={"request": request}
        )

    async def faults(self, run_id: str) -> list[dict]:
        return (await self._send("GET", f"/internal/sandbox/runs/{run_id}/faults"))["faults"]

    async def finalize(self, run_id: str, wait_ms: int) -> dict:
        # finalize may wait up to wait_ms for in-flight tool calls.
        return await self._send(
            "POST",
            f"/internal/sandbox/runs/{run_id}/finalize",
            json={"wait_ms": wait_ms},
            timeout=wait_ms / 1000 + 10,
        )


class AgentClient(_Http):
    service = "agents"

    async def execution_profile(self):
        return await self._send("GET", "/internal/qa/execution-profile")

    async def analyze(self, body: dict) -> dict:
        return await self._send("POST", "/internal/qa/analyze", json=body)

    async def design(self, body: dict) -> dict:
        return await self._send("POST", "/internal/qa/design", json=body, timeout=85)

    async def start(self, body: dict) -> dict:
        return await self._send("POST", "/internal/agent-runs", json=body)

    async def status(self, run_id: str) -> dict:
        return await self._send("GET", f"/internal/agent-runs/{run_id}")

    async def resume(self, run_id: str, body: dict) -> dict:
        return await self._send("POST", f"/internal/agent-runs/{run_id}/resume", json=body)

    async def events(self, run_id: str, after_sequence: int) -> list[dict]:
        data = await self._send(
            "GET",
            f"/internal/agent-runs/{run_id}/events",
            params={"after_sequence": after_sequence},
        )
        return data["events"]
