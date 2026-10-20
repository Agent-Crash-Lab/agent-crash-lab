package com.agentcrashlab.mcp.internal;

import java.util.List;
import java.util.Map;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.ToolException;
import com.agentcrashlab.mcp.domain.Approvals;
import com.agentcrashlab.mcp.domain.PurchasePayload;
import com.agentcrashlab.mcp.domain.RunFinalizer;
import com.agentcrashlab.mcp.domain.RunSetup;
import com.agentcrashlab.mcp.fault.FaultRules;

/**
 * Harness → MCP 내부 API (MCP_SPEC 3장). X-Internal-Token은 InternalTokenFilter가 검사한다.
 */
@RestController
@RequestMapping("/internal/sandbox/runs")
class SandboxRunController {

	private final RunSetup runSetup;

	private final Approvals approvals;

	private final FaultRules faultRules;

	private final RunFinalizer finalizer;

	SandboxRunController(RunSetup runSetup, Approvals approvals, FaultRules faultRules, RunFinalizer finalizer) {
		this.runSetup = runSetup;
		this.approvals = approvals;
		this.faultRules = faultRules;
		this.finalizer = finalizer;
	}

	record FaultRuleBody(@NotBlank String faultId, @NotBlank String toolName, @NotBlank String trigger,
			@Min(1) int maxAppliedCount, @NotBlank String targetErrorCode) {
	}

	record InitializeBody(@NotBlank String runId, @NotBlank String scenarioId, @NotBlank String serverPolicyVersion,
			@NotBlank String fixtureId, @NotBlank String requestedBy, @NotNull List<@Valid FaultRuleBody> faults) {
	}

	/** 3.1 실행 초기화 */
	@PostMapping
	@ResponseStatus(HttpStatus.CREATED)
	RunSetup.Result initialize(@Valid @RequestBody InitializeBody body) {
		List<RunSetup.FaultRule> faults = body.faults()
			.stream()
			.map(f -> new RunSetup.FaultRule(f.faultId(), f.toolName(), f.trigger(), f.maxAppliedCount(),
					f.targetErrorCode()))
			.toList();
		return this.runSetup.initialize(new RunSetup.Command(body.runId(), body.scenarioId(), body.serverPolicyVersion(),
				body.fixtureId(), body.requestedBy(), faults));
	}

	record ApprovalRequestBody(@NotNull Map<String, Object> request) {
	}

	/** 3.2 승인 요청 등록. 구매 Agent가 interrupt한 뒤 Harness가 호출한다 */
	@PostMapping("/{runId}/approval-requests")
	@ResponseStatus(HttpStatus.CREATED)
	Approvals.PendingApproval registerApproval(@PathVariable String runId, @Valid @RequestBody ApprovalRequestBody body) {
		PurchasePayload request;
		try {
			request = PurchasePayload.fromMap(body.request());
		}
		catch (ToolException ex) {
			throw ApiException.badRequest("VALIDATION_ERROR", "Invalid request payload");
		}
		return this.approvals.register(runId, request);
	}

	/** 3.3 사고 주입 상태 */
	@GetMapping("/{runId}/faults")
	Map<String, Object> faults(@PathVariable String runId) {
		return Map.of("faults", this.faultRules.statuses(runId));
	}

	record FinalizeBody(Long waitMs) {
	}

	/** 3.4 상태 확정. 응답은 drafts oracle-observation 형식 */
	@PostMapping("/{runId}/finalize")
	Map<String, Object> finalizeRun(@PathVariable String runId, @RequestBody(required = false) FinalizeBody body) {
		long waitMs = (body != null && body.waitMs() != null) ? body.waitMs() : 5000;
		return this.finalizer.finalizeRun(runId, waitMs);
	}

}
