from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.tools.errors import ToolError
from agents.tools.mcp import McpTools, parse_result


def response(text, error=False):
    return SimpleNamespace(content=[SimpleNamespace(text=text)], isError=error)


def test_parses_content_text_and_not_structured_content():
    data = response('{"request_id":"REQ-1", "order_id":"PO-1"}')
    data.structuredContent = {"order_id": "wrong"}
    assert parse_result(data)["order_id"] == "PO-1"


@pytest.mark.parametrize(
    "code",
    [
        "TOOL_TIMEOUT",
        "PERMISSION_DENIED",
        "VALIDATION_ERROR",
        "APPROVAL_REQUIRED",
        "APPROVAL_REJECTED",
        "APPROVAL_MISMATCH",
        "REQUEST_PAYLOAD_MISMATCH",
        "INTERNAL_ERROR",
    ],
)
def test_error_codes(code):
    import json

    with pytest.raises(ToolError) as error:
        parse_result(
            response(
                json.dumps(
                    {
                        "error": {
                            "code": code,
                            "message": "secret",
                            "retryable": code == "TOOL_TIMEOUT",
                        }
                    }
                ),
                True,
            )
        )
    assert error.value.code == code and "secret" not in str(error.value)


@pytest.mark.parametrize("value", ["not json", "[]", "null", '{"error":{}}'])
def test_bad_response(value):
    with pytest.raises(ToolError, match="INVALID_RESPONSE"):
        parse_result(response(value))


@pytest.mark.asyncio
async def test_adapter_does_not_retry_writes():
    tools = McpTools("http://localhost:8081/mcp", "test-bearer", 10)
    tools.session = SimpleNamespace(call_tool=AsyncMock(side_effect=TimeoutError))
    with pytest.raises(ToolError, match="TOOL_TIMEOUT"):
        await tools.call("create_purchase_order", {"request": {}, "approval_id": "AP-1"})
    assert tools.session.call_tool.await_count == 1
