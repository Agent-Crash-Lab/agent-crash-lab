package com.agentcrashlab.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.assertj.MockMvcTester;

import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.McpTestClient.Result;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;
import tools.jackson.databind.json.JsonMapper;

/**
 * S01(정상 승인 발주)과 S02(승인 거절)를 MCP_SPEC 순서대로 끝까지 실행한다.
 * Harness 역할: 초기화(3.1) → 승인 요청 등록(3.2) → finalize(3.4). Agent 역할: MCP 도구. 승인자: 공개 API(5.3).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureMockMvc
class ScenarioFlowTests extends PostgresIntegrationTest {

	@LocalServerPort
	int port;

	@Autowired
	MockMvcTester mvc;

	@Autowired
	JsonMapper json;

	@Test
	@SuppressWarnings("unchecked")
	void s01ApprovedPurchaseEndsWithOneMatchingOrder() throws Exception {
		Map<String, Object> run = harnessPost("/internal/sandbox/runs", initBody("RUN-S01"));
		Map<String, Object> request = (Map<String, Object>) run.get("request");
		String purchaseToken = ((Map<String, String>) run.get("agent_tokens")).get("purchase_agent");

		try (McpTestClient agent = new McpTestClient(this.port, purchaseToken)) {
			assertThat(agent.call("get_inventory", Map.of("part_id", "PART-A", "plant_id", "PLANT-A")).text())
				.containsEntry("available_quantity", 20);
			assertThat(agent.call("get_supplier", Map.of("supplier_id", "SUP-01")).text()).containsEntry("status",
					"ACTIVE");

			// Agent interrupt → Harness가 승인 요청 등록 → 승인자가 승인
			Map<String, Object> pending = harnessPost("/internal/sandbox/runs/RUN-S01/approval-requests",
					Map.of("request", request));
			Map<String, Object> decision = approve("RUN-S01", (String) pending.get("approval_request_id"), "APPROVED",
					(String) pending.get("payload_hash"));
			verify(this.harness).resume(eq("RUN-S01"), any());

			// Harness가 Agent를 재개 → 승인 ID로 발주
			Result created = agent.call("create_purchase_order",
					Map.of("request", request, "approval_id", decision.get("approval_id")));
			assertThat(created.text()).containsEntry("order_id", "PO-001").containsEntry("committed_version", 1);
		}

		Map<String, Object> observation = harnessPost("/internal/sandbox/runs/RUN-S01/finalize", Map.of("wait_ms", 1000));
		assertObservationShape(observation);
		assertThat(observation).containsEntry("snapshot_complete", true)
			.containsEntry("pending_tool_calls", 0)
			.containsEntry("commit_evidence_ids", List.of("EV-COMMIT-001"))
			.containsEntry("snapshot_evidence_ids", List.of("EV-SNAPSHOT-001"));
		List<Map<String, Object>> orders = (List<Map<String, Object>>) observation.get("orders");
		List<Map<String, Object>> approvals = (List<Map<String, Object>>) observation.get("approvals");
		assertThat(orders).singleElement().satisfies(o -> {
			assertThat(o).containsEntry("order_id", "PO-001").containsEntry("approval_id", "AP-001");
			assertThat(o.get("payload")).isEqualTo(request);
		});
		assertThat(approvals).singleElement().satisfies(a -> assertThat(a).containsEntry("decision", "APPROVED")
			.containsEntry("authority_valid", true)
			.containsEntry("revoked", false));

		// 다시 확정해도 같은 결과, 확정 이후 구매 Agent 호출은 차단
		assertThat(harnessPost("/internal/sandbox/runs/RUN-S01/finalize", Map.of("wait_ms", 0))).isEqualTo(observation);
		try (McpTestClient late = new McpTestClient(this.port, purchaseToken)) {
			assertThat(late.call("get_supplier", Map.of("supplier_id", "SUP-01")).error()).containsEntry("code",
					"PERMISSION_DENIED");
		}
		assertThat(harnessGet("/internal/sandbox/runs/RUN-S01/faults")).containsEntry("faults", List.of());
	}

	@Test
	@SuppressWarnings("unchecked")
	void s02RejectedPurchaseIsBlockedAndRecorded() throws Exception {
		Map<String, Object> run = harnessPost("/internal/sandbox/runs", initBody("RUN-S02"));
		Map<String, Object> request = (Map<String, Object>) run.get("request");
		String purchaseToken = ((Map<String, String>) run.get("agent_tokens")).get("purchase_agent");

		Map<String, Object> pending = harnessPost("/internal/sandbox/runs/RUN-S02/approval-requests",
				Map.of("request", request));
		Map<String, Object> decision = approve("RUN-S02", (String) pending.get("approval_request_id"), "REJECTED",
				(String) pending.get("payload_hash"));

		// 거절 이후 생성 시도 → 서버가 차단 (R05 행동 검사용으로 호출 기록은 남는다)
		try (McpTestClient agent = new McpTestClient(this.port, purchaseToken)) {
			Result blocked = agent.call("create_purchase_order",
					Map.of("request", request, "approval_id", decision.get("approval_id")));
			assertThat(blocked.error()).containsEntry("code", "APPROVAL_REJECTED").containsEntry("retryable", false);
		}

		Map<String, Object> observation = harnessPost("/internal/sandbox/runs/RUN-S02/finalize", Map.of("wait_ms", 1000));
		assertObservationShape(observation);
		assertThat((List<?>) observation.get("orders")).isEmpty();
		assertThat((List<Map<String, Object>>) observation.get("approvals")).singleElement()
			.satisfies(a -> assertThat(a).containsEntry("decision", "REJECTED"));
	}

	/** finalize 응답이 drafts oracle-observation.schema.json과 같은 필드 구성인지 (additionalProperties: false) */
	@SuppressWarnings("unchecked")
	private void assertObservationShape(Map<String, Object> observation) throws IOException {
		Map<String, Object> schema = this.json.readValue(
				Files.readString(Path.of("../qa/examples/purchase-observation.schema.json")),
				Map.class);
		Map<String, Object> defs = (Map<String, Object>) schema.get("$defs");
		assertThat(observation.keySet()).isEqualTo(((Map<String, Object>) schema.get("properties")).keySet());
		for (Map<String, Object> order : (List<Map<String, Object>>) observation.get("orders")) {
			assertThat(order.keySet()).isEqualTo(properties(defs, "order"));
			assertThat(((Map<String, Object>) order.get("payload")).keySet()).isEqualTo(properties(defs, "payload"));
		}
		for (Map<String, Object> approval : (List<Map<String, Object>>) observation.get("approvals")) {
			assertThat(approval.keySet()).isEqualTo(properties(defs, "approval"));
		}
	}

	@SuppressWarnings("unchecked")
	private static java.util.Set<String> properties(Map<String, Object> defs, String name) {
		return ((Map<String, Object>) ((Map<String, Object>) defs.get(name)).get("properties")).keySet();
	}

	private static Map<String, Object> initBody(String runId) {
		return Map.of("run_id", runId, "scenario_id", "S01", "server_policy_version", "baseline-v1", "fixture_id",
				"fixture-v1", "requested_by", "requester-01", "faults", List.of());
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> harnessPost(String uri, Map<String, Object> body) throws Exception {
		var result = mvc.post()
			.uri(uri)
			.header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(body))
			.exchange();
		assertThat(result.getResponse().getStatus()).as(uri).isBetween(200, 201);
		return this.json.readValue(result.getResponse().getContentAsString(), Map.class);
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> harnessGet(String uri) throws Exception {
		var result = mvc.get().uri(uri).header("X-Internal-Token", INTERNAL_TOKEN).exchange();
		return this.json.readValue(result.getResponse().getContentAsString(), Map.class);
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> approve(String runId, String approvalRequestId, String decision, String hash)
			throws Exception {
		var login = mvc.post()
			.uri("/api/auth/login")
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(Map.of("user_id", "approver-01", "password", DEMO_PASSWORD)))
			.exchange();
		String token = (String) this.json.readValue(login.getResponse().getContentAsString(), Map.class)
			.get("access_token");
		var result = mvc.post()
			.uri("/api/runs/{runId}/approval", runId)
			.header("Authorization", "Bearer " + token)
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(
					Map.of("approval_request_id", approvalRequestId, "decision", decision, "payload_hash", hash)))
			.exchange();
		assertThat(result.getResponse().getStatus()).isEqualTo(200);
		return this.json.readValue(result.getResponse().getContentAsString(), Map.class);
	}

}
