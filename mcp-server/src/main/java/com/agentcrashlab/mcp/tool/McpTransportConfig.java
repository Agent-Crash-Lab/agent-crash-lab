package com.agentcrashlab.mcp.tool;

import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.json.jackson3.JacksonMcpJsonMapper;
import org.springframework.ai.mcp.customizer.McpSyncServerCustomizer;
import org.springframework.ai.mcp.server.common.autoconfigure.properties.McpServerStreamableHttpProperties;
import org.springframework.ai.mcp.server.webmvc.transport.WebMvcStreamableServerTransportProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpHeaders;

import tools.jackson.databind.json.JsonMapper;

/**
 * MCP 전송 계층. 자동설정의 기본 빈을 대신해, HTTP Authorization 헤더를 도구 실행까지 넘긴다 (MCP_SPEC 1.1).
 * 도구는 요청 스레드가 아닌 곳에서 실행될 수 있어서 스레드 로컬 대신 MCP의 transport context를 쓴다.
 */
@Configuration(proxyBeanMethods = false)
class McpTransportConfig {

	@Bean
	WebMvcStreamableServerTransportProvider webMvcStreamableServerTransportProvider(
			@Qualifier("mcpServerJsonMapper") JsonMapper mcpJsonMapper, McpServerStreamableHttpProperties properties) {
		return WebMvcStreamableServerTransportProvider.builder()
			.jsonMapper(new JacksonMcpJsonMapper(mcpJsonMapper))
			.mcpEndpoint(properties.getMcpEndpoint())
			.keepAliveInterval(properties.getKeepAliveInterval())
			.disallowDelete(properties.isDisallowDelete())
			.contextExtractor(request -> {
				String authorization = request.headers().firstHeader(HttpHeaders.AUTHORIZATION);
				return McpTransportContext.create(Map.of(ToolRunner.AUTHORIZATION, (authorization != null) ? authorization : ""));
			})
			.build();
	}

	/**
	 * SDK의 도구 입력 스키마 검사를 끈다. SDK는 위반 시 JSON이 아닌 문장으로 응답하는데,
	 * MCP_SPEC 1.2는 content[0].text가 항상 JSON이어야 한다. 인자 검사는 ToolArgs·PurchasePayload가
	 * 같은 규칙으로 하고 VALIDATION_ERROR 봉투로 응답한다.
	 * 자동설정의 기본 customizer(immediateExecution)를 대신하므로 그 설정도 함께 넣는다.
	 */
	@Bean
	@Primary
	McpSyncServerCustomizer crashLabMcpServerCustomizer() {
		return spec -> spec.immediateExecution(true).validateToolInputs(false);
	}

	/** 도구 실행용. 10초 상한을 넘기면 응답은 먼저 돌려주고 작업은 끝까지 진행된다 */
	@Bean(destroyMethod = "close")
	ExecutorService toolExecutor() {
		return Executors.newVirtualThreadPerTaskExecutor();
	}

}
