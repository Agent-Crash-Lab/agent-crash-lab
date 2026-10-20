package com.agentcrashlab.mcp.auth;

/**
 * Agent 토큰에 묶인 실행과 Agent 종류. 도구 인자가 아니라 이 값으로 실행을 정한다 (MCP_SPEC 1.1).
 */
public record AgentPrincipal(String runId, AgentKind kind) {
}
