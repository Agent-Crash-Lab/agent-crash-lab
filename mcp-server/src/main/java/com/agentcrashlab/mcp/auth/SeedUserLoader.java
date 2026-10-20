package com.agentcrashlab.mcp.auth;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.domain.SeedFixtures;

/**
 * 서버 시작 시 seed 사용자를 로그인 계정으로 등록한다 (MCP_SPEC 5.3). 실행별로 복제하지 않는 공용 데이터다.
 */
@Component
class SeedUserLoader implements ApplicationRunner {

	private final SeedFixtures fixtures;

	private final UserSessions sessions;

	SeedUserLoader(SeedFixtures fixtures, UserSessions sessions) {
		this.fixtures = fixtures;
		this.sessions = sessions;
	}

	@Override
	public void run(ApplicationArguments args) {
		for (SeedFixtures.User user : this.fixtures.read().seed().users()) {
			this.sessions.upsertUser(user.userId(), user.roles(), user.purchasingOrgId());
		}
	}

}
