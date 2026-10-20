package com.agentcrashlab.mcp.internal;

import static com.agentcrashlab.mcp.support.Fixtures.initRun;
import static com.agentcrashlab.mcp.support.Fixtures.insertDecision;
import static com.agentcrashlab.mcp.support.Fixtures.seedRequest;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.assertj.MockMvcTester;

import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.domain.Approvals;
import com.agentcrashlab.mcp.domain.PurchasePayload;
import com.agentcrashlab.mcp.domain.RunFinalizer;
import com.agentcrashlab.mcp.domain.RunSetup;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;
import tools.jackson.databind.json.JsonMapper;

/**
 * finalize(MCP_SPEC 3.4) 이후: 승인 변경을 받지 않고, snapshot 근거는 같은 ID에 항상 같은 내용이다.
 */
@AutoConfigureMockMvc
class FinalizedRunTests extends PostgresIntegrationTest {

	static final CurrentUser APPROVER = new CurrentUser("approver-01", List.of("APPROVER"), "PUR-A");

	@Autowired
	MockMvcTester mvc;

	@Autowired
	RunSetup runSetup;

	@Autowired
	Approvals approvals;

	@Autowired
	RunFinalizer finalizer;

	@Autowired
	JdbcClient jdbc;

	@Autowired
	JsonMapper json;

	@Test
	void lateApprovalIsRejectedAfterFinalize() {
		initRun(this.runSetup, "RUN-Z1", "baseline-v1");
		Approvals.PendingApproval pending = this.approvals.register("RUN-Z1", PurchasePayload.fromMap(seedRequest()));

		// 승인 대기 중에 시험이 끝났다 (예: 승인 대기 만료)
		Map<String, Object> snapshot = this.finalizer.finalizeRun("RUN-Z1", 0);
		assertThat((List<?>) snapshot.get("approvals")).isEmpty();

		// 뒤늦은 승인·새 승인 요청은 받지 않는다
		assertThatThrownBy(() -> this.approvals.decide("RUN-Z1", pending.approvalRequestId(), "APPROVED",
				pending.payloadHash(), APPROVER))
			.isInstanceOf(ApiException.class)
			.extracting(e -> ((ApiException) e).code())
			.isEqualTo("RUN_FINALIZED");
		assertThat(mvc.post()
			.uri("/internal/sandbox/runs/RUN-Z1/approval-requests")
			.header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content(this.json.writeValueAsString(Map.of("request", seedRequest())))).hasStatus(HttpStatus.CONFLICT)
			.bodyJson()
			.extractingPath("$.error.code")
			.isEqualTo("RUN_FINALIZED");

		assertThat(jdbc.sql("SELECT count(*) FROM approval WHERE run_id = 'RUN-Z1'").query(Integer.class).single())
			.isZero();
		assertThat(this.finalizer.finalizeRun("RUN-Z1", 0)).isEqualTo(snapshot);
	}

	@Test
	void snapshotEvidenceKeepsTheSameContent() {
		initRun(this.runSetup, "RUN-Z2", "baseline-v1");
		Map<String, Object> snapshot = this.finalizer.finalizeRun("RUN-Z2", 0);
		assertThat(snapshot).containsEntry("snapshot_evidence_ids", List.of("EV-SNAPSHOT-001"));

		// API를 거치지 않은 늦은 쓰기가 생겨도 (예: 확정 뒤 끝난 느린 호출) 확정된 snapshot은 바뀌지 않는다
		insertDecision(this.jdbc, "RUN-Z2", "AP-LATE", "APPROVED", true);

		assertThat(this.finalizer.finalizeRun("RUN-Z2", 0)).as("finalize 재호출").isEqualTo(snapshot);
		assertThat(this.finalizer.currentState("RUN-Z2")).as("get_business_state").isEqualTo(snapshot);
	}

	@Test
	void stateBeforeFinalizeIsLiveAndMarkedIncomplete() {
		initRun(this.runSetup, "RUN-Z3", "baseline-v1");
		insertDecision(this.jdbc, "RUN-Z3", "AP-001", "APPROVED", true);

		Map<String, Object> live = this.finalizer.currentState("RUN-Z3");
		assertThat(live).containsEntry("snapshot_complete", false).containsEntry("snapshot_evidence_ids", List.of());
		assertThat((List<?>) live.get("approvals")).hasSize(1);
	}

}
