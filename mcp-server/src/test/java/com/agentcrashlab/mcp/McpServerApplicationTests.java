package com.agentcrashlab.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.assertj.MockMvcTester;
import org.springframework.test.web.servlet.assertj.MvcTestResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/**
 * 1단계 골격 검증: /health, REST snake_case, MCP 프로토콜 필드명 유지.
 */
@AutoConfigureMockMvc
class McpServerApplicationTests extends PostgresIntegrationTest {

	@Autowired
	MockMvcTester mvc;

	@Test
	void healthEndpointIsUp() {
		assertThat(mvc.get().uri("/health"))
			.hasStatusOk()
			.bodyJson()
			.extractingPath("$.status")
			.isEqualTo("UP");
	}

	@Test
	void restJsonUsesSnakeCase() {
		assertThat(mvc.get().uri("/test/sample"))
			.hasStatusOk()
			.bodyJson()
			.extractingPath("$.sample_field")
			.isEqualTo("ok");
	}

	@Test
	void mcpEndpointKeepsProtocolFieldNames() throws Exception {
		String initialize = """
				{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
				  "protocolVersion":"2025-06-18","capabilities":{},
				  "clientInfo":{"name":"skeleton-test","version":"0.0.0"}}}
				""";

		MvcTestResult result = mvc.post()
			.uri("/mcp")
			.contentType(MediaType.APPLICATION_JSON)
			.header("Accept", "application/json, text/event-stream")
			.content(initialize)
			.exchange();

		assertThat(result).hasStatusOk();
		String body = result.getResponse().getContentAsString();
		assertThat(body).contains("\"serverInfo\"", "\"protocolVersion\"", "agent-crash-lab-mcp");
		assertThat(body).doesNotContain("server_info", "protocol_version");
	}

	@TestConfiguration
	static class SampleControllerConfig {

		@Bean
		SampleController sampleController() {
			return new SampleController();
		}

	}

	@RestController
	static class SampleController {

		record Sample(String sampleField) {
		}

		@GetMapping("/test/sample")
		Sample sample() {
			return new Sample("ok");
		}

	}

}
