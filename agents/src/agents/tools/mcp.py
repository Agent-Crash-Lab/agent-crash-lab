"""MCP v1 SDK transport, following PR #5; no transport-level write retries."""

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

from agents.tools.errors import ToolError

ERRORS = {
    "TOOL_TIMEOUT",
    "PERMISSION_DENIED",
    "VALIDATION_ERROR",
    "APPROVAL_REQUIRED",
    "APPROVAL_REJECTED",
    "APPROVAL_MISMATCH",
    "REQUEST_PAYLOAD_MISMATCH",
    "SUPPLIER_NOT_QUALIFIED",
    "INTERNAL_ERROR",
}
PURCHASE_TOOLS = {
    "get_supplier_eligibility",
    "get_inventory",
    "get_supplier",
    "create_purchase_order",
    "get_order_by_request",
}
INVESTIGATION_TOOLS = {
    "search_manufacturing_knowledge",
    "get_failed_checks",
    "get_run_trace",
    "get_business_state",
    "search_failure_guides",
}


def parse_result(result) -> dict:
    try:
        data = json.loads(result.content[0].text)
        if not isinstance(data, dict):
            raise ValueError
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise ToolError("INVALID_RESPONSE") from exc
    if result.isError:
        error = data.get("error", {})
        if not isinstance(error, dict):
            raise ToolError("INVALID_RESPONSE")
        code = error.get("code")
        if code not in ERRORS or type(error.get("retryable")) is not bool:
            raise ToolError("INVALID_RESPONSE")
        raise ToolError(code, retryable=error["retryable"])
    if "error" in data:
        raise ToolError("INVALID_RESPONSE")
    return data


class McpTools:
    def __init__(self, url: str, token: str, timeout: float):
        self.url, self.token, self.timeout = url, token, timeout
        self.session = None
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        try:
            async with asyncio.timeout(self.timeout):
                streams = await self.stack.enter_async_context(
                    streamablehttp_client(
                        self.url,
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=self.timeout,
                        sse_read_timeout=self.timeout,
                    )
                )
                self.session = await self.stack.enter_async_context(
                    ClientSession(
                        streams[0], streams[1], read_timeout_seconds=timedelta(seconds=self.timeout)
                    )
                )
                await self.session.initialize()
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    async def __aexit__(self, *args):
        await self.stack.aclose()

    async def _perform(self, operation):
        try:
            return await operation
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ToolError("TOOL_TIMEOUT", retryable=True) from exc
        except McpError as exc:
            if exc.error.code in {408, -32001}:
                raise ToolError("TOOL_TIMEOUT", retryable=True) from exc
            raise ToolError("PROTOCOL_ERROR") from exc
        except httpx.HTTPError as exc:
            raise ToolError("TRANSPORT_ERROR", retryable=True) from exc

    async def call(self, name: str, arguments: dict) -> dict:
        return parse_result(await self._perform(self.session.call_tool(name, arguments)))

    async def resource(self, uri: str) -> str:
        response = await self._perform(self.session.read_resource(uri))
        try:
            return response.contents[0].text
        except (IndexError, AttributeError) as exc:
            raise ToolError("INVALID_RESPONSE") from exc
