package com.agentcrashlab.mcp.auth;

import java.sql.Array;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;
import com.agentcrashlab.mcp.common.Hashing;

/**
 * 로그인 계정(seed 사용자)과 로그인 토큰 (MCP_SPEC 5.3). 토큰은 Agent 토큰과 같은 방식으로 해시만 저장한다.
 */
@Component
public class UserSessions {

	private final JdbcClient jdbc;

	private final CrashLabProperties properties;

	private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

	UserSessions(JdbcClient jdbc, CrashLabProperties properties) {
		this.jdbc = jdbc;
		this.properties = properties;
	}

	public record Session(String token, Instant expiresAt, CurrentUser user) {
	}

	/** 서버 시작 시 seed 사용자를 등록한다. 비밀번호는 모든 계정 공통 개발용 값 */
	public void upsertUser(String userId, List<String> roles, String purchasingOrgId) {
		this.jdbc.sql("""
				INSERT INTO app_user (user_id, password_hash, roles, purchasing_org_id) VALUES (?, ?, ?, ?)
				ON CONFLICT (user_id) DO UPDATE
				SET password_hash = EXCLUDED.password_hash, roles = EXCLUDED.roles,
				    purchasing_org_id = EXCLUDED.purchasing_org_id""")
			.params(userId, this.encoder.encode(this.properties.demoUserPassword()), roles.toArray(String[]::new),
					purchasingOrgId)
			.update();
	}

	public Session login(String userId, String password) {
		String passwordHash = this.jdbc.sql("SELECT password_hash FROM app_user WHERE user_id = ?")
			.param(userId)
			.query(String.class)
			.optional()
			.orElse(null);
		if (passwordHash == null || password == null || !this.encoder.matches(password, passwordHash)) {
			throw ApiException.unauthorized();
		}
		String token = Tokens.generate();
		Instant expiresAt = Instant.now().plus(this.properties.userSessionTtl());
		this.jdbc.sql("INSERT INTO user_session (token_hash, user_id, expires_at) VALUES (?, ?, ?)")
			.params(Hashing.sha256(token), userId, Timestamp.from(expiresAt))
			.update();
		return new Session(token, expiresAt, find(userId).orElseThrow());
	}

	/** Authorization 헤더로 로그인 사용자를 찾는다. 없으면 401 */
	public CurrentUser require(String authorization) {
		String token = Tokens.bearer(authorization);
		if (token == null) {
			throw ApiException.unauthorized();
		}
		return this.jdbc.sql("""
				SELECT u.user_id, u.roles, u.purchasing_org_id FROM user_session s
				JOIN app_user u ON u.user_id = s.user_id
				WHERE s.token_hash = ? AND s.expires_at > now()""")
			.param(Hashing.sha256(token))
			.query((rs, row) -> user(rs.getString("user_id"), rs.getArray("roles"), rs.getString("purchasing_org_id")))
			.optional()
			.orElseThrow(ApiException::unauthorized);
	}

	public Optional<CurrentUser> find(String userId) {
		return this.jdbc.sql("SELECT user_id, roles, purchasing_org_id FROM app_user WHERE user_id = ?")
			.param(userId)
			.query((rs, row) -> user(rs.getString("user_id"), rs.getArray("roles"), rs.getString("purchasing_org_id")))
			.optional();
	}

	private static CurrentUser user(String userId, Array roles, String purchasingOrgId) throws SQLException {
		return new CurrentUser(userId, List.of((String[]) roles.getArray()), purchasingOrgId);
	}

}
