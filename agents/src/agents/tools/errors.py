"""Safe tool error codes shared by mock tools and the MCP adapter."""


class ToolError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        known = {
            "TOOL_TIMEOUT",
            "PERMISSION_DENIED",
            "VALIDATION_ERROR",
            "APPROVAL_REQUIRED",
            "APPROVAL_REJECTED",
            "APPROVAL_MISMATCH",
            "REQUEST_PAYLOAD_MISMATCH",
            "INTERNAL_ERROR",
            "INVALID_RESPONSE",
            "PROTOCOL_ERROR",
            "TRANSPORT_ERROR",
            "ADAPTER_ERROR",
        }
        self.code = code if code in known else "ADAPTER_ERROR"
        super().__init__(self.code)
        self.retryable = retryable
