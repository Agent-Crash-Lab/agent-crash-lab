package com.agentcrashlab.mcp.auth;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.common.CrashLabProperties;
import com.agentcrashlab.mcp.common.Hashing;

/**
 * 실행 전용 Agent 토큰 (MCP_SPEC 1.1). 원문은 발급 응답에만 담고 DB에는 해시만 남긴다.
 */
@Component
public class AgentTokens {

	private final JdbcClient jdbc;

	private final CrashLabProperties properties;

	AgentTokens(JdbcClient jdbc, CrashLabProperties properties) {
		this.jdbc = jdbc;
		this.properties = properties;
	}

	public String issue(String runId, AgentKind kind) {
		String token = Tokens.generate();
		this.jdbc.sql("INSERT INTO agent_token (token_hash, run_id, agent_kind, expires_at) VALUES (?, ?, ?, ?)")
			.params(Hashing.sha256(token), runId, kind.name(),
					Timestamp.from(Instant.now().plus(this.properties.agentTokenTtl())))
			.update();
		return token;
	}

	/** Authorization 헤더 값으로 찾는다. 없거나 만료·폐기됐으면 empty */
	public Optional<AgentPrincipal> resolve(String authorization) {
		String token = Tokens.bearer(authorization);
		if (token == null) {
			return Optional.empty();
		}
		return this.jdbc.sql("""
				SELECT run_id, agent_kind FROM agent_token
				WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > now()""")
			.param(Hashing.sha256(token))
			.query((rs, row) -> new AgentPrincipal(rs.getString("run_id"), AgentKind.valueOf(rs.getString("agent_kind"))))
			.optional();
	}

	public void revoke(String runId, AgentKind kind) {
		this.jdbc.sql("UPDATE agent_token SET revoked_at = now() WHERE run_id = ? AND agent_kind = ? AND revoked_at IS NULL")
			.params(runId, kind.name())
			.update();
	}

}
