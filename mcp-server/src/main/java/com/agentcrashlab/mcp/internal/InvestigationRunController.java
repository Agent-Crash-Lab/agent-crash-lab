package com.agentcrashlab.mcp.internal;

import java.util.Map;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.agentcrashlab.mcp.domain.InvestigationRuns;

/**
 * Harness → MCP 내부 API (MCP_SPEC 3.6). 생산·품질 실행을 조사 전용으로 등록하고 조사 Agent 토큰을 발급한다.
 */
@RestController
class InvestigationRunController {

	private final InvestigationRuns runs;

	InvestigationRunController(InvestigationRuns runs) {
		this.runs = runs;
	}

	record RegisterBody(@NotBlank String runId, @NotBlank @Pattern(regexp = "PRODUCTION|QUALITY") String agentType,
			@NotBlank String scenarioId, @NotBlank String requestedBy) {
	}

	record Registered(String runId, String agentType, Map<String, String> agentTokens) {
	}

	@PostMapping("/internal/investigation-runs")
	@ResponseStatus(HttpStatus.CREATED)
	Registered register(@Valid @RequestBody RegisterBody body) {
		String token = this.runs.registerHarnessRun(body.runId(), body.agentType(), body.scenarioId(),
				body.requestedBy());
		return new Registered(body.runId(), body.agentType(), Map.of("investigation_agent", token));
	}

}
