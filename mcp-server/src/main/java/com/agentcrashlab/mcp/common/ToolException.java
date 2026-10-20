package com.agentcrashlab.mcp.common;

/**
 * MCP 도구 업무 오류. 도구 응답은 isError=true와 오류 봉투로 바뀐다 (MCP_SPEC 1.2).
 * 메시지는 코드별 고정 문구만 쓴다. 내부 상태(사고 주입 등)를 Agent에 노출하지 않기 위해서다.
 */
public class ToolException extends RuntimeException {

	private final ToolErrorCode code;

	public ToolException(ToolErrorCode code) {
		super(code.defaultMessage());
		this.code = code;
	}

	public ToolErrorCode code() {
		return this.code;
	}

}
