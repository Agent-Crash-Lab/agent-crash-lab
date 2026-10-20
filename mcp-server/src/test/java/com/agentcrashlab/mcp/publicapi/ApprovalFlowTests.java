package com.agentcrashlab.mcp.publicapi;

import static com.agentcrashlab.mcp.support.Fixtures.initRun;
import static com.agentcrashlab.mcp.support.Fixtures.seedRequest;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import java.util.Map;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.assertj.MockMvcTester;
import org.springframework.test.web.servlet.assertj.MvcTestResult;

import com.agentcrashlab.mcp.domain.Approvals;
import com.agentcrashlab.mcp.domain.RunSetup;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;
import tools.jackson.databind.json.JsonMapper;

/** MCP_SPEC 3.2 승인 요청 등록, 5.3 로그인·승인, 4.1 Harness 재개 요청 */
@AutoConfigureMockMvc
class ApprovalFlowTests extends PostgresIntegrationTest {

	static final String SEED_HASH = "44f349414b0973935825d379579a30cf137ec3ab49c2b28bc9923f46d4e8bf26";

	@Autowired
	MockMvcTester mvc;

	@Autowired
	RunSetup runSetup;

	@Autowired
	JdbcClient jdbc;

	@Autowired
	JsonMapper json;

	@Test
	void registersOnePendingApprovalForTheRegisteredRequest() {
		initRun(this.runSetup, "RUN-A1", "baseline-v1");

		MvcTestResult first = registerApproval("RUN-A1", seedRequest());
		assertThat(first).hasStatus(HttpStatus.CREATED);
		assertThat(first).bodyJson().extractingPath("$.approval_request_id").isEqualTo("APR-001");
		assertThat(first).bodyJson().extractingPath("$.payload_hash").isEqualTo(SEED_HASH);
		assertThat(first).bodyJson().extractingPath("$.expires_at").isNotNull();

		assertThat(registerApproval("RUN-A1", seedRequest())).hasStatus(HttpStatus.CONFLICT);

		Map<String, Object> changed = seedRequest();
		changed.put("quantity", 80);
		assertThat(registerApproval("RUN-A1", changed)).hasStatus(HttpStatus.BAD_REQUEST)
			.bodyJson()
			.extractingPath("$.error.code")
			.isEqualTo("REQUEST_PAYLOAD_MISMATCH");
		assertThat(registerApproval("RUN-NONE", seedRequest())).hasStatus(HttpStatus.NOT_FOUND);
	}

	@Test
	void loginRequiresTheDemoPassword() {
		assertThat(login("approver-01", "wrong")).hasStatus(HttpStatus.UNAUTHORIZED);
		assertThat(login("nobody", DEMO_PASSWORD)).hasStatus(HttpStatus.UNAUTHORIZED);

		MvcTestResult ok = login("approver-01", DEMO_PASSWORD);
		assertThat(ok).hasStatusOk();
		assertThat(ok).bodyJson().extractingPath("$.token_type").isEqualTo("Bearer");
		assertThat(ok).bodyJson().extractingPath("$.roles[0]").isEqualTo("APPROVER");
	}

	@Test
	void approverDecidesAndHarnessIsAskedToResume() {
		initRun(this.runSetup, "RUN-A2", "baseline-v1");
		registerApproval("RUN-A2", seedRequest());

		MvcTestResult approved = decide("RUN-A2", token("approver-01"), "APR-001", "APPROVED", SEED_HASH);
		assertThat(approved).hasStatusOk();
		assertThat(approved).bodyJson().extractingPath("$.approval_id").isEqualTo("AP-001");
		assertThat(approved).bodyJson().extractingPath("$.approver_id").isEqualTo("approver-01");

		ArgumentCaptor<Approvals.Decision> sent = ArgumentCaptor.forClass(Approvals.Decision.class);
		verify(this.harness).resume(eq("RUN-A2"), sent.capture());
		assertThat(sent.getValue().approvalId()).isEqualTo("AP-001");
		assertThat(sent.getValue().decision()).isEqualTo("APPROVED");
		assertThat(sent.getValue().payloadHash()).isEqualTo(SEED_HASH);
		// Harness로 보내는 본문은 MCP_SPEC 4.1의 snake_case 필드
		assertThat(this.json.writeValueAsString(sent.getValue())).contains("\"approval_id\":\"AP-001\"",
				"\"approver_id\":\"approver-01\"", "\"payload_hash\"", "\"decided_at\"");

		assertThat(jdbc.sql("SELECT authority_valid FROM approval WHERE run_id = 'RUN-A2' AND approval_id = 'AP-001'")
			.query(Boolean.class)
			.single()).isTrue();

		// 이미 결정된 요청은 다시 결정할 수 없다
		assertThat(decide("RUN-A2", token("approver-01"), "APR-001", "REJECTED", SEED_HASH))
			.hasStatus(HttpStatus.CONFLICT);
	}

	@Test
	void decisionRequiresApproverAndTheShownPayload() {
		initRun(this.runSetup, "RUN-A3", "baseline-v1");
		registerApproval("RUN-A3", seedRequest());

		assertThat(decide("RUN-A3", null, "APR-001", "APPROVED", SEED_HASH)).hasStatus(HttpStatus.UNAUTHORIZED);
		assertThat(decide("RUN-A3", token("requester-01"), "APR-001", "APPROVED", SEED_HASH))
			.hasStatus(HttpStatus.FORBIDDEN);
		assertThat(decide("RUN-A3", token("approver-01"), "APR-001", "APPROVED", "0".repeat(64)))
			.hasStatus(HttpStatus.CONFLICT);
		assertThat(decide("RUN-A3", token("approver-01"), "APR-404", "APPROVED", SEED_HASH))
			.hasStatus(HttpStatus.NOT_FOUND);
		verify(this.harness, never()).resume(any(), any());
	}

	private MvcTestResult registerApproval(String runId, Map<String, Object> request) {
		return mvc.post()
			.uri("/internal/sandbox/runs/{runId}/approval-requests", runId)
			.header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(Map.of("request", request)))
			.exchange();
	}

	private MvcTestResult login(String userId, String password) {
		return mvc.post()
			.uri("/api/auth/login")
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(Map.of("user_id", userId, "password", password)))
			.exchange();
	}

	private String token(String userId) {
		try {
			String body = login(userId, DEMO_PASSWORD).getResponse().getContentAsString();
			return (String) this.json.readValue(body, Map.class).get("access_token");
		}
		catch (java.io.UnsupportedEncodingException ex) {
			throw new IllegalStateException(ex);
		}
	}

	private MvcTestResult decide(String runId, String token, String approvalRequestId, String decision, String hash) {
		var request = mvc.post()
			.uri("/api/runs/{runId}/approval", runId)
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(
					Map.of("approval_request_id", approvalRequestId, "decision", decision, "payload_hash", hash)));
		if (token != null) {
			request = request.header("Authorization", "Bearer " + token);
		}
		return request.exchange();
	}

}
