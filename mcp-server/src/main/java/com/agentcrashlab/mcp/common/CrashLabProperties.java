package com.agentcrashlab.mcp.common;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * application.yml의 crashlab.* 설정.
 *
 * @param internalApiToken 내부 API 헤더 X-Internal-Token 값. 비어 있으면 내부 API를 모두 거부한다
 * @param harnessUrl Harness 주소 (MCP_SPEC 4장)
 * @param mcpUrl Agent가 접속할 MCP 주소 (MCP_SPEC 3.1 응답)
 * @param fixturesDir 저장소 fixtures/ 위치. Path로 받으면 웹 서버 실행 시 웹 리소스 경로로 해석되어 "../"가 거부되므로 문자열로 받는다
 * @param demoUserPassword seed 사용자 공통 개발용 비밀번호 (MCP_SPEC 5.3)
 * @param toolTimeout 도구 응답 상한 (MCP_SPEC 1.5)
 * @param approvalWait 승인 대기 상한 (MCP_SPEC 1.8)
 * @param agentTokenTtl Agent 토큰 유효 시간. 조사 Agent가 finalize 이후에도 써야 하므로 실행 상한보다 길게 둔다
 * @param userSessionTtl 로그인 토큰 유효 시간
 */
@ConfigurationProperties("crashlab")
public record CrashLabProperties(String internalApiToken, String harnessUrl, String mcpUrl, String fixturesDir,
		String demoUserPassword, Duration toolTimeout, Duration approvalWait, Duration agentTokenTtl,
		Duration userSessionTtl) {
}
