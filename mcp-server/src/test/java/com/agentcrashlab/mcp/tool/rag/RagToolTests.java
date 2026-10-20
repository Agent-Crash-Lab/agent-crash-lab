package com.agentcrashlab.mcp.tool.rag;

import static com.agentcrashlab.mcp.support.Fixtures.seedRequest;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Map;

import io.modelcontextprotocol.spec.McpError;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.domain.Approvals;
import com.agentcrashlab.mcp.domain.PurchasePayload;
import com.agentcrashlab.mcp.domain.RunFinalizer;
import com.agentcrashlab.mcp.domain.RunSetup;
import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.McpTestClient.Result;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/**
 * 조사 Agent용 rag-mcp 도구와 지침 Resource (MCP_SPEC 1.4).
 * 대상 실행은 S03 + B0로 중복 발주가 생긴 상태에서 조사한다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class RagToolTests extends PostgresIntegrationTest {

	@LocalServerPort
	int port;

	@Autowired
	RunSetup runSetup;

	@Autowired
	Approvals approvals;

	@Autowired
	RunFinalizer finalizer;

	/** S03 + B0: 사고 → 재시도 → 발주 2건. 조사 Agent 토큰을 돌려준다 */
	private Map<String, String> duplicateRun(String runId, boolean finalize) {
		RunSetup.FaultRule fault = new RunSetup.FaultRule("FLT-001", "create_purchase_order",
				"AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE", 1, "TOOL_TIMEOUT");
		Map<String, String> tokens = this.runSetup
			.initialize(new RunSetup.Command(runId, "S03", "baseline-v1", "fixture-v1", "requester-01", List.of(fault)))
			.agentTokens();
		Approvals.PendingApproval pending = this.approvals.register(runId, PurchasePayload.fromMap(seedRequest()));
		String approvalId = this.approvals
			.decide(runId, pending.approvalRequestId(), "APPROVED", pending.payloadHash(),
					new CurrentUser("approver-01", List.of("APPROVER"), "PUR-A"))
			.approvalId();
		try (McpTestClient agent = new McpTestClient(this.port, tokens.get("purchase_agent"))) {
			agent.call("create_purchase_order", Map.of("request", seedRequest(), "approval_id", approvalId));
			agent.call("create_purchase_order", Map.of("request", seedRequest(), "approval_id", approvalId));
		}
		if (finalize) {
			this.finalizer.finalizeRun(runId, 1000);
		}
		return tokens;
	}

	@Test
	void businessStateShowsTheDuplicateWithEvidence() {
		Map<String, String> tokens = duplicateRun("RUN-R1", true);
		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"))) {
			Result state = investigator.call("get_business_state", Map.of("run_id", "RUN-R1"));
			assertThat(state.isError()).isFalse();
			assertThat(state.text()).containsEntry("snapshot_complete", true)
				.containsEntry("commit_evidence_ids", List.of("EV-COMMIT-001", "EV-COMMIT-002"))
				.containsEntry("snapshot_evidence_ids", List.of("EV-SNAPSHOT-001"));
			assertThat((List<?>) state.text().get("orders")).hasSize(2);
		}
		Map<String, Object> fetched = event("RUN-R1", "EVIDENCE_FETCHED");
		assertThat(fetched).containsEntry("node_id", "investigator")
			.containsEntry("evidence_ids", List.of("EV-SNAPSHOT-001", "EV-COMMIT-001", "EV-COMMIT-002"));
	}

	@Test
	void businessStateBeforeFinalizeIsNotComplete() {
		Map<String, String> tokens = duplicateRun("RUN-R2", false);
		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"))) {
			assertThat(investigator.call("get_business_state", Map.of("run_id", "RUN-R2")).text())
				.containsEntry("snapshot_complete", false);
		}
	}

	@Test
	void runTraceCombinesHarnessEventsAndToolCalls() {
		Map<String, String> tokens = duplicateRun("RUN-R3", true);
		when(this.harness.runEvents("RUN-R3")).thenReturn(List.of(Map.of("run_id", "RUN-R3", "event_id", "EVT-005",
				"sequence", 5, "event_type", "BUSINESS_COMMITTED", "evidence_ids", List.of("EV-COMMIT-001"))));

		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"))) {
			Result trace = investigator.call("get_run_trace", Map.of("run_id", "RUN-R3"));
			assertThat((List<?>) trace.text().get("events")).hasSize(1);
			@SuppressWarnings("unchecked")
			List<Map<String, Object>> calls = (List<Map<String, Object>>) trace.text().get("tool_calls");
			List<Map<String, Object>> creates = calls.stream()
				.filter(c -> "create_purchase_order".equals(c.get("tool")))
				.toList();
			assertThat(creates).hasSize(2);
			assertThat(creates.get(0)).containsEntry("is_error", true).containsEntry("error_code", "TOOL_TIMEOUT");
			assertThat(creates.get(1)).containsEntry("is_error", false);
			assertThat(creates.get(0)).doesNotContainKey("run_id"); // 조사 Agent가 다른 실행 근거로 오인하지 않게
		}
	}

	@Test
	void failedChecksComeFromHarness() {
		Map<String, String> tokens = duplicateRun("RUN-R4", true);
		Map<String, Object> check = Map.of("run_id", "RUN-R4", "check_id", "CHK-DUPLICATE", "rule_id", "R03",
				"rule_version", "0.1.0", "scope", "business_state", "verdict", "FAIL", "reason", "같은 요청 발주 2건",
				"evidence_ids", List.of("EV-SNAPSHOT-001", "EV-COMMIT-001", "EV-COMMIT-002"));
		when(this.harness.failedChecks("RUN-R4")).thenReturn(List.of(check));

		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"))) {
			Result checks = investigator.call("get_failed_checks", Map.of("run_id", "RUN-R4"));
			assertThat(checks.text()).containsEntry("run_id", "RUN-R4").containsEntry("checks", List.of(check));
		}
	}

	@Test
	void harnessOutageIsRetryableInternalError() {
		Map<String, String> tokens = duplicateRun("RUN-R5", true);
		when(this.harness.failedChecks("RUN-R5")).thenThrow(new IllegalStateException("connection refused"));
		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"))) {
			assertThat(investigator.call("get_failed_checks", Map.of("run_id", "RUN-R5")).error())
				.containsEntry("code", "INTERNAL_ERROR")
				.containsEntry("retryable", true);
		}
	}

	@Test
	void onlyTheInvestigatorOfThisRunCanUseRagTools() {
		Map<String, String> tokens = duplicateRun("RUN-R6", true);
		duplicateRun("RUN-R7", true);
		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"));
				McpTestClient purchaser = new McpTestClient(this.port, tokens.get("purchase_agent"))) {
			assertThat(investigator.call("get_business_state", Map.of("run_id", "RUN-R7")).error())
				.as("다른 실행 조회").containsEntry("code", "PERMISSION_DENIED");
			assertThat(investigator.call("create_purchase_order",
					Map.of("request", seedRequest(), "approval_id", "AP-001")).error())
				.as("조사 Agent는 업무 변경 불가").containsEntry("code", "PERMISSION_DENIED");
			assertThat(purchaser.call("search_failure_guides", Map.of("query", "중복")).error())
				.as("구매 Agent 토큰은 finalize 후 폐기").containsEntry("code", "PERMISSION_DENIED");
		}
	}

	@Test
	void guideSearchAndResourceRead() {
		Map<String, String> tokens = duplicateRun("RUN-R8", true);
		try (McpTestClient investigator = new McpTestClient(this.port, tokens.get("investigation_agent"))) {
			Result search = investigator.call("search_failure_guides", Map.of("query", "중복 처리 재시도"));
			@SuppressWarnings("unchecked")
			List<Map<String, Object>> results = (List<Map<String, Object>>) search.text().get("results");
			assertThat(results).isNotEmpty().hasSizeLessThanOrEqualTo(3);
			Map<String, Object> top = results.get(0);
			assertThat(top).containsKeys("document_id", "version", "title", "location", "snippet", "resource_uri");
			assertThat(top.get("resource_uri")).isEqualTo("guide://" + top.get("document_id") + "/" + top.get("version"));
			assertThat(top.get("document_id")).isIn("idempotency-guide", "retry-error-guide");

			assertThat(investigator.resourceUris()).contains("guide://idempotency-guide/v1", "guide://approval-policy/v1");
			assertThat(investigator.readResource("guide://idempotency-guide/v1")).startsWith("# 중복 처리");
		}
		assertThat(event("RUN-R8", "GUIDE_RETRIEVED")).containsEntry("node_id", "guide");
	}

	@Test
	void guideResourceRequiresInvestigatorToken() {
		try (McpTestClient anonymous = new McpTestClient(this.port, null)) {
			assertThatThrownBy(() -> anonymous.readResource("guide://idempotency-guide/v1"))
				.isInstanceOf(McpError.class);
		}
	}

	private Map<String, Object> event(String runId, String type) {
		return deliveredEvents(runId).stream()
			.filter(e -> type.equals(e.get("event_type")))
			.findFirst()
			.orElseThrow();
	}

}
