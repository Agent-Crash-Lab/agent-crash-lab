package com.agentcrashlab.mcp.harness;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import com.agentcrashlab.mcp.common.CrashLabProperties;
import com.agentcrashlab.mcp.domain.Approvals;
import tools.jackson.databind.json.JsonMapper;

@Component
class RestHarnessClient implements HarnessClient {

	private final RestClient rest;

	private final JsonMapper json;

	RestHarnessClient(CrashLabProperties properties, JsonMapper json) {
		JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(
				HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build());
		factory.setReadTimeout(Duration.ofSeconds(10));
		this.rest = RestClient.builder()
			.requestFactory(factory)
			.baseUrl(properties.harnessUrl())
			.defaultHeader("X-Internal-Token", properties.internalApiToken())
			.build();
		this.json = json;
	}

	@Override
	public void resume(String runId, Approvals.Decision decision) {
		// 본문은 앱 공통 매퍼(snake_case)로 직접 직렬화한다
		this.rest.post()
			.uri("/internal/runs/{runId}/resume", runId)
			.contentType(MediaType.APPLICATION_JSON)
			.body(this.json.writeValueAsString(decision))
			.retrieve()
			.toBodilessEntity();
	}

	@Override
	public List<Map<String, Object>> failedChecks(String runId) {
		return list(this.rest.get()
			.uri("/internal/runs/{runId}/checks?verdicts=FAIL,INCONCLUSIVE", runId)
			.retrieve()
			.body(String.class), "checks");
	}

	@Override
	public List<Map<String, Object>> runEvents(String runId) {
		return list(this.rest.get().uri("/internal/runs/{runId}/events", runId).retrieve().body(String.class),
				"events");
	}

	@SuppressWarnings("unchecked")
	private List<Map<String, Object>> list(String body, String field) {
		Object items = this.json.readValue(body, Map.class).get(field);
		if (!(items instanceof List<?>)) {
			throw new IllegalStateException("Harness response has no '" + field + "' list");
		}
		return (List<Map<String, Object>>) items;
	}

	@Override
	public void submitEvent(String runId, Map<String, Object> event) {
		this.rest.post()
			.uri("/internal/runs/{runId}/events", runId)
			.contentType(MediaType.APPLICATION_JSON)
			.body(this.json.writeValueAsString(event))
			.retrieve()
			.toBodilessEntity();
	}

}
