package com.agentcrashlab.mcp.tool.business;

import static com.agentcrashlab.mcp.support.Fixtures.initRun;
import static com.agentcrashlab.mcp.support.Fixtures.insertDecision;
import static com.agentcrashlab.mcp.support.Fixtures.seedRequest;
import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.simple.JdbcClient;

import com.agentcrashlab.mcp.domain.RunSetup;
import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.McpTestClient.Result;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/**
 * 구매 도구 4개를 실제 MCP 클라이언트로 호출한다 (MCP_SPEC 1.2~1.6).
 * 기대값은 Agent가 검사하는 조건(agents/src/agents/graph/purchase.py)을 그대로 따른다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class BusinessToolTests extends PostgresIntegrationTest {

	@LocalServerPort
	int port;

	@Autowired
	RunSetup runSetup;

	@Autowired
	JdbcClient jdbc;

	McpTestClient purchaseAgent(String runId) {
		return new McpTestClient(this.port, initRun(this.runSetup, runId, "baseline-v1").agentTokens().get("purchase_agent"));
	}

	@Test
	void listsTheFourPurchaseTools() {
		try (McpTestClient agent = purchaseAgent("RUN-B0")) {
			assertThat(agent.toolNames()).contains("get_inventory", "get_supplier", "create_purchase_order",
					"get_order_by_request");
		}
	}

	@Test
	void readToolsReturnWhatTheAgentChecks() {
		try (McpTestClient agent = purchaseAgent("RUN-B1")) {
			Result inventory = agent.call("get_inventory", Map.of("part_id", "PART-A", "plant_id", "PLANT-A"));
			assertThat(inventory.isError()).isFalse();
			assertThat(inventory.text()).containsEntry("part_id", "PART-A")
				.containsEntry("plant_id", "PLANT-A")
				.containsEntry("available_quantity", 20)
				.containsEntry("unit", "EA")
				.containsEntry("inventory_version", 1);

			Result supplier = agent.call("get_supplier", Map.of("supplier_id", "SUP-01"));
			assertThat(supplier.text()).containsEntry("supplier_id", "SUP-01")
				.containsEntry("status", "ACTIVE")
				.containsEntry("unit_price_minor", 12000)
				.containsEntry("currency", "KRW")
				.containsEntry("supplier_version", 1);
		}
	}

	@Test
	void missingTokenIsPermissionDenied() {
		try (McpTestClient anonymous = new McpTestClient(this.port, null)) {
			Result result = anonymous.call("get_supplier", Map.of("supplier_id", "SUP-01"));
			assertThat(result.isError()).isTrue();
			assertThat(result.error()).containsEntry("code", "PERMISSION_DENIED").containsEntry("retryable", false);
		}
	}

	@Test
	void investigationAgentCannotCallPurchaseToolsAndTheAttemptIsRecorded() {
		RunSetup.Result run = initRun(this.runSetup, "RUN-B2", "baseline-v1");
		try (McpTestClient investigator = new McpTestClient(this.port, run.agentTokens().get("investigation_agent"))) {
			Result result = investigator.call("get_supplier", Map.of("supplier_id", "SUP-01"));
			assertThat(result.error()).containsEntry("code", "PERMISSION_DENIED");
		}
		assertThat(jdbc.sql("SELECT error_code FROM tool_call WHERE run_id = 'RUN-B2'").query(String.class).single())
			.isEqualTo("PERMISSION_DENIED");
	}

	@Test
	void invalidArgumentsAreValidationErrors() {
		try (McpTestClient agent = purchaseAgent("RUN-B3")) {
			assertThat(agent.call("get_inventory", Map.of("part_id", "PART-A")).error()).containsEntry("code",
					"VALIDATION_ERROR");
			assertThat(agent.call("get_inventory", Map.of("part_id", "NOPE", "plant_id", "PLANT-A")).error())
				.containsEntry("code", "VALIDATION_ERROR");
			assertThat(agent.call("get_supplier", Map.of("supplier_id", "SUP-01", "run_id", "RUN-X")).error())
				.containsEntry("code", "VALIDATION_ERROR");
		}
	}

	@Test
	void createIsBlockedWithoutValidApproval() {
		try (McpTestClient agent = purchaseAgent("RUN-B4")) {
			assertThat(create(agent, seedRequest(), "AP-404").error()).containsEntry("code", "APPROVAL_REQUIRED");

			insertDecision(jdbc, "RUN-B4", "AP-001", "REJECTED", true);
			assertThat(create(agent, seedRequest(), "AP-001").error()).containsEntry("code", "APPROVAL_REJECTED");

			insertDecision(jdbc, "RUN-B4", "AP-002", "APPROVED", false);
			assertThat(create(agent, seedRequest(), "AP-002").error()).containsEntry("code", "APPROVAL_REQUIRED");

			Map<String, Object> changed = seedRequest();
			changed.put("quantity", 200);
			insertDecision(jdbc, "RUN-B4", "AP-003", "APPROVED", true);
			assertThat(create(agent, changed, "AP-003").error()).containsEntry("code", "REQUEST_PAYLOAD_MISMATCH");
		}
		assertThat(orderCount("RUN-B4")).isZero();
		assertThat(jdbc.sql("SELECT count(*) FROM tool_call WHERE run_id = 'RUN-B4' AND tool = 'create_purchase_order'")
			.query(Integer.class)
			.single()).isEqualTo(4);
	}

	@Test
	void approvedCreateCommitsOrderWithEvidenceAndB0AllowsDuplicates() {
		insertDecisionAfterInit("RUN-B5");
		try (McpTestClient agent = new McpTestClient(this.port, this.purchaseToken)) {
			Result first = create(agent, seedRequest(), "AP-001");
			assertThat(first.isError()).isFalse();
			assertThat(first.text()).containsEntry("request_id", "REQ-001")
				.containsEntry("order_id", "PO-001")
				.containsEntry("status", "CREATED")
				.containsEntry("committed_version", 1);

			// B0(baseline-v1): 같은 요청 재시도는 새 발주를 만든다
			assertThat(create(agent, seedRequest(), "AP-001").text()).containsEntry("order_id", "PO-002");

			Result orders = agent.call("get_order_by_request", Map.of("request_id", "REQ-001"));
			assertThat((List<?>) orders.text().get("orders")).hasSize(2);
		}
		assertThat(jdbc.sql("SELECT commit_evidence_id FROM purchase_order WHERE run_id = 'RUN-B5' ORDER BY commit_sequence")
			.query(String.class)
			.list()).containsExactly("EV-COMMIT-001", "EV-COMMIT-002");
		assertThat(jdbc.sql("SELECT count(*) FROM evidence WHERE run_id = 'RUN-B5' AND kind = 'BUSINESS_COMMITTED'")
			.query(Integer.class)
			.single()).isEqualTo(2);
		assertThat(jdbc.sql("SELECT count(*) FROM tool_call WHERE run_id = 'RUN-B5' AND status = 'IN_FLIGHT'")
			.query(Integer.class)
			.single()).isZero();
	}

	private String purchaseToken;

	private void insertDecisionAfterInit(String runId) {
		this.purchaseToken = initRun(this.runSetup, runId, "baseline-v1").agentTokens().get("purchase_agent");
		insertDecision(jdbc, runId, "AP-001", "APPROVED", true);
	}

	private static Result create(McpTestClient agent, Map<String, Object> request, String approvalId) {
		return agent.call("create_purchase_order", Map.of("request", request, "approval_id", approvalId));
	}

	private int orderCount(String runId) {
		return jdbc.sql("SELECT count(*) FROM purchase_order WHERE run_id = ?").param(runId).query(Integer.class).single();
	}

}
