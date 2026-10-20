package com.agentcrashlab.mcp.publicapi;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.Set;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
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

	/** 재개 요청 시도 횟수 (첫 시도 + 재시도 2회) */
	static final int RESUME_ATTEMPTS = 3;

	private static final Duration RESUME_BACKOFF = Duration.ofMillis(200);

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

		// 같은 결정을 다시 보내면 decide()가 기존 결정을 돌려주므로, 재개 요청도 다시 전달된다
		Approvals.Decision decision = this.approvals.decide(runId, body.approvalRequestId(), body.decision(),
				body.payloadHash(), user);
		ApprovalResponse response = new ApprovalResponse(decision.approvalId(), decision.requestId(),
				decision.decision(), decision.approverId(), decision.decidedAt());
		resumeWithRetry(runId, decision, response);
		return response;
	}

	/**
	 * Harness 재개 요청(4.1). 일시적인 끊김은 짧게 재시도한다. 끝내 실패하면 결정은 저장된 채로 503을 돌려준다.
	 * Harness는 같은 approval_id를 한 번만 재개하므로 재시도·재요청으로 중복 재개되지 않는다.
	 */
	private void resumeWithRetry(String runId, Approvals.Decision decision, ApprovalResponse response) {
		RuntimeException last = null;
		for (int attempt = 1; attempt <= RESUME_ATTEMPTS; attempt++) {
			try {
				this.harness.resume(runId, decision);
				return;
			}
			catch (RuntimeException ex) {
				last = ex;
				log.warn("Harness resume attempt {}/{} failed for run {} approval {}: {}", attempt, RESUME_ATTEMPTS,
						runId, decision.approvalId(), ex.getMessage());
				if (attempt < RESUME_ATTEMPTS) {
					sleep(RESUME_BACKOFF.multipliedBy(attempt));
				}
			}
		}
		log.error("Harness resume failed for run {} approval {}", runId, decision.approvalId(), last);
		throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "HARNESS_RESUME_FAILED",
				"The decision was saved, but the agent could not be resumed. Send the same decision again to retry.",
				Map.of("decision_saved", true, "approval", response));
	}

	private static void sleep(Duration duration) {
		try {
			Thread.sleep(duration);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
		}
	}

}
