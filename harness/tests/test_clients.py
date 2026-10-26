import httpx
import pytest

from harness.clients import AgentClient, ClientError


async def test_malformed_success_response_is_a_safe_client_error():
    client = AgentClient("http://agents", "test-token")
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url="http://agents",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="invalid secret")),
    )
    try:
        with pytest.raises(ClientError) as error:
            await client.status("INV-RUN-001")
        assert error.value.code == "INVALID_RESPONSE"
        assert "secret" not in str(error.value)
    finally:
        await client.close()
