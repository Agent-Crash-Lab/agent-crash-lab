package com.agentcrashlab.mcp.domain;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.auth.AgentTokens;
import com.agentcrashlab.mcp.common.ApiException;

/**
 * 실행의 업무 유형. 구매 실행은 이 서버 DB가 원본이고, 생산·품질 실행은 Harness 모의 환경이 원본이다.
 * 생산·품질 실행은 조사 전용으로만 등록해 조사 Agent 토큰과 조사 도구 호출 기록의 기준으로 쓴다.
 */
@Component
public class InvestigationRuns {

	public static final String PURCHASE = "PURCHASE";

	static final String HARNESS_SANDBOX = "harness-sandbox";

	private final JdbcClient jdbc;

	private final AgentTokens tokens;

	InvestigationRuns(JdbcClient jdbc, AgentTokens tokens) {
		this.jdbc = jdbc;
		this.tokens = tokens;
	}

	/** 같은 실행을 다시 등록하면 이전 조사 토큰을 폐기하고 새로 발급한다. 업무 유형은 바꿀 수 없다 */
	@Transactional
	public String registerHarnessRun(String runId, String agentType, String scenarioId, String requestedBy) {
		this.jdbc.sql("""
				INSERT INTO run_context (run_id, scenario_id, server_policy_version, fixture_id, requested_by, agent_type)
				VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (run_id) DO NOTHING""")
			.params(runId, scenarioId, HARNESS_SANDBOX, HARNESS_SANDBOX, requestedBy, agentType)
			.update();
		if (!agentType.equals(agentType(runId))) {
			throw ApiException.conflict("Run is already registered with a different agent type");
		}
		this.tokens.revoke(runId, AgentKind.INVESTIGATION_AGENT);
		return this.tokens.issue(runId, AgentKind.INVESTIGATION_AGENT);
	}

	/** 토큰이 있는 실행은 항상 run_context 행이 있다 (외래 키) */
	public String agentType(String runId) {
		return this.jdbc.sql("SELECT agent_type FROM run_context WHERE run_id = ?").param(runId).query(String.class).single();
	}

}
