package com.agentcrashlab.mcp.internal;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.assertj.MockMvcTester;

import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/** MCP_SPEC 3.1 실행 초기화와 내부 토큰 검사 */
@AutoConfigureMockMvc
class RunSetupTests extends PostgresIntegrationTest {

	@Autowired
	MockMvcTester mvc;

	@Autowired
	JdbcClient jdbc;

	static String body(String runId, String fixtureId) {
		return """
				{"run_id":"%s","scenario_id":"S01","server_policy_version":"baseline-v1",
				 "fixture_id":"%s","requested_by":"requester-01","faults":[]}""".formatted(runId, fixtureId);
	}

	@Test
	void rejectsMissingOrWrongInternalToken() {
		assertThat(mvc.post().uri("/internal/sandbox/runs").contentType(MediaType.APPLICATION_JSON)
			.content(body("RUN-S1", "fixture-v1"))).hasStatus(HttpStatus.UNAUTHORIZED)
			.bodyJson()
			.extractingPath("$.error.code")
			.isEqualTo("UNAUTHORIZED");
		assertThat(mvc.post().uri("/internal/sandbox/runs").header("X-Internal-Token", "wrong")
			.contentType(MediaType.APPLICATION_JSON)
			.content(body("RUN-S1", "fixture-v1"))).hasStatus(HttpStatus.UNAUTHORIZED);
	}

	@Test
	void initializesRunFromSeed() {
		var result = mvc.post().uri("/internal/sandbox/runs").header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(body("RUN-S2", "fixture-v1"))
			.exchange();

		assertThat(result).hasStatus(HttpStatus.CREATED);
		assertThat(result).bodyJson().extractingPath("$.run_id").isEqualTo("RUN-S2");
		assertThat(result).bodyJson().extractingPath("$.server_policy_version").isEqualTo("baseline-v1");
		assertThat(result).bodyJson().extractingPath("$.request.request_id").isEqualTo("REQ-001");
		assertThat(result).bodyJson().extractingPath("$.request.plant_id").isEqualTo("PLANT-A");
		assertThat(result).bodyJson().extractingPath("$.agent_tokens.purchase_agent").asString().hasSizeGreaterThan(20);
		assertThat(result).bodyJson().extractingPath("$.agent_tokens.investigation_agent").asString().hasSizeGreaterThan(20);

		assertThat(count("inventory", "RUN-S2")).isEqualTo(1);
		assertThat(count("supplier", "RUN-S2")).isEqualTo(2);
		assertThat(count("approved_supply_source", "RUN-S2")).isEqualTo(2);
		assertThat(count("purchase_request", "RUN-S2")).isEqualTo(1);
		assertThat(count("agent_token", "RUN-S2")).isEqualTo(2);
	}

	@Test
	void rejectsDuplicateRunAndUnknownFixture() {
		mvc.post().uri("/internal/sandbox/runs").header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(body("RUN-S3", "fixture-v1"))
			.exchange();

		assertThat(mvc.post().uri("/internal/sandbox/runs").header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(body("RUN-S3", "fixture-v1"))).hasStatus(HttpStatus.CONFLICT);
		assertThat(mvc.post().uri("/internal/sandbox/runs").header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(body("RUN-S4", "fixture-v9"))).hasStatus(HttpStatus.BAD_REQUEST)
			.bodyJson()
			.extractingPath("$.error.code")
			.isEqualTo("VALIDATION_ERROR");
	}

	@Test
	void seedUsersAreLoaded() {
		var roles = jdbc.sql("SELECT array_to_string(roles, ',') FROM app_user WHERE user_id = 'approver-01'")
			.query(String.class)
			.single();
		assertThat(roles).isEqualTo("APPROVER");
	}

	private int count(String table, String runId) {
		return jdbc.sql("SELECT count(*) FROM " + table + " WHERE run_id = ?").param(runId).query(Integer.class).single();
	}

}
