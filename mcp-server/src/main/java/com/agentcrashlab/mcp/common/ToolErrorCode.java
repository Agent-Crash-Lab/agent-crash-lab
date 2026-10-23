package com.agentcrashlab.mcp.common;

/**
 * MCP 도구 오류 코드 (MCP_SPEC 1.5, qa/examples/purchase/tools.json tool_errors).
 */
public enum ToolErrorCode {

	TOOL_TIMEOUT(true, "The operation timed out before a response was received."),
	PERMISSION_DENIED(false, "Permission denied."),
	VALIDATION_ERROR(false, "Invalid arguments."),
	APPROVAL_REQUIRED(false, "A valid approval is required."),
	APPROVAL_REJECTED(false, "The approval was rejected."),
	APPROVAL_MISMATCH(false, "The request does not match the approved payload."),
	REQUEST_PAYLOAD_MISMATCH(false, "The request does not match the registered request."),
	SUPPLIER_NOT_QUALIFIED(false, "The supplier is not authorized for this item, plant and purchasing organization."),
	INTERNAL_ERROR(true, "Internal server error.");

	private final boolean retryable;

	private final String defaultMessage;

	ToolErrorCode(boolean retryable, String defaultMessage) {
		this.retryable = retryable;
		this.defaultMessage = defaultMessage;
	}

	public boolean retryable() {
		return this.retryable;
	}

	public String defaultMessage() {
		return this.defaultMessage;
	}

}
