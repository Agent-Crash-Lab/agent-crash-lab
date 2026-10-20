package com.agentcrashlab.mcp.publicapi;

import java.time.Instant;
import java.util.Set;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.auth.UserSessions;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.domain.Approvals;
import com.agentcrashlab.mcp.harness.HarnessClient;

/** 공개 API 승인·거절 (MCP_SPEC 1.8, 5.3). 기록 후 Harness에 Agent 재개를 요청한다 (4.1) */
@RestController
class ApprovalController {

	private static final Logger log = LoggerFactory.getLogger(ApprovalController.class);

	private static final Set<String> DECISIONS = Set.of("APPROVED", "REJECTED");

	private final UserSessions sessions;

	private final Approvals approvals;

	private final HarnessClient harness;

	ApprovalController(UserSessions sessions, Approvals approvals, HarnessClient harness) {
		this.sessions = sessions;
		this.approvals = approvals;
		this.harness = harness;
	}

	record ApprovalBody(@NotBlank String approvalRequestId, @NotBlank String decision, @NotBlank String payloadHash) {
	}

	record ApprovalResponse(String approvalId, String requestId, String decision, String approverId,
			Instant decidedAt) {
	}

	@PostMapping("/api/runs/{runId}/approval")
	ApprovalResponse decide(@PathVariable String runId,
			@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
			@Valid @RequestBody ApprovalBody body) {
		CurrentUser user = this.sessions.require(authorization);
		if (!user.hasRole(CurrentUser.APPROVER)) {
			throw ApiException.forbidden("APPROVER role required");
		}
		if (!DECISIONS.contains(body.decision())) {
			throw ApiException.badRequest("VALIDATION_ERROR", "decision must be APPROVED or REJECTED");
		}

		Approvals.Decision decision = this.approvals.decide(runId, body.approvalRequestId(), body.decision(),
				body.payloadHash(), user);
		try {
			this.harness.resume(runId, decision);
		}
		catch (RuntimeException ex) {
			// 결정은 이미 저장됐다. Harness는 같은 approval_id를 한 번만 재개하므로 운영자가 다시 보내도 안전하다.
			log.error("Harness resume failed for run {} approval {}", runId, decision.approvalId(), ex);
		}
		return new ApprovalResponse(decision.approvalId(), decision.requestId(), decision.decision(),
				decision.approverId(), decision.decidedAt());
	}

}
