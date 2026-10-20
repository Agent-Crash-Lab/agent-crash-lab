package com.agentcrashlab.mcp.publicapi;

import static com.agentcrashlab.mcp.support.Fixtures.initRun;
import static com.agentcrashlab.mcp.support.Fixtures.seedRequest;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
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

	@Test
	void transientResumeFailureIsRetried() {
		initRun(this.runSetup, "RUN-A4", "baseline-v1");
		registerApproval("RUN-A4", seedRequest());
		doThrow(new IllegalStateException("connection refused")).doNothing()
			.when(this.harness)
			.resume(eq("RUN-A4"), any());

		assertThat(decide("RUN-A4", token("approver-01"), "APR-001", "APPROVED", SEED_HASH)).hasStatusOk();
		verify(this.harness, times(2)).resume(eq("RUN-A4"), any());
	}

	@Test
	@SuppressWarnings("unchecked")
	void resumeFailureIsReportedAndTheSameDecisionCanBeResent() {
		initRun(this.runSetup, "RUN-A5", "baseline-v1");
		registerApproval("RUN-A5", seedRequest());
		String approver = token("approver-01");

		// Harness가 계속 응답하지 않으면: 결정은 저장되고 503으로 알린다
		doThrow(new IllegalStateException("connection refused")).when(this.harness).resume(eq("RUN-A5"), any());
		MvcTestResult failed = decide("RUN-A5", approver, "APR-001", "APPROVED", SEED_HASH);
		assertThat(failed).hasStatus(HttpStatus.SERVICE_UNAVAILABLE);
		assertThat(failed).bodyJson().extractingPath("$.error.code").isEqualTo("HARNESS_RESUME_FAILED");
		assertThat(failed).bodyJson().extractingPath("$.error.details.decision_saved").isEqualTo(true);
		assertThat(failed).bodyJson().extractingPath("$.error.details.approval.approval_id").isEqualTo("AP-001");
		verify(this.harness, times(ApprovalController.RESUME_ATTEMPTS)).resume(eq("RUN-A5"), any());

		// Harness가 돌아온 뒤 같은 결정을 다시 보내면: 기존 결정을 돌려주고 재개 요청을 다시 보낸다
		doNothing().when(this.harness).resume(eq("RUN-A5"), any());
		MvcTestResult resent = decide("RUN-A5", approver, "APR-001", "APPROVED", SEED_HASH);
		assertThat(resent).hasStatusOk();
		assertThat(resent).bodyJson().extractingPath("$.approval_id").isEqualTo("AP-001");
		verify(this.harness, times(ApprovalController.RESUME_ATTEMPTS + 1)).resume(eq("RUN-A5"), any());

		assertThat(jdbc.sql("SELECT count(*) FROM approval WHERE run_id = 'RUN-A5'").query(Integer.class).single())
			.as("결정은 한 번만 저장된다")
			.isEqualTo(1);
		ArgumentCaptor<Map<String, Object>> events = ArgumentCaptor.forClass(Map.class);
		verify(this.harness, atLeastOnce()).submitEvent(eq("RUN-A5"), events.capture());
		assertThat(events.getAllValues().stream().filter(e -> "APPROVAL_DECIDED".equals(e.get("event_type"))))
			.as("재요청은 새 결정 이벤트를 만들지 않는다")
			.hasSize(1);

		// 다른 결정으로 바꾸는 건 재시도가 아니므로 여전히 409
		assertThat(decide("RUN-A5", approver, "APR-001", "REJECTED", SEED_HASH)).hasStatus(HttpStatus.CONFLICT);
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
