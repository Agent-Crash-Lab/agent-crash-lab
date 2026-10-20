package com.agentcrashlab.mcp.support;

import java.net.http.HttpRequest;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.ReadResourceRequest;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import io.modelcontextprotocol.spec.McpSchema.TextResourceContents;

import tools.jackson.databind.json.JsonMapper;

/**
 * 테스트용 MCP 클라이언트. Agent처럼 HTTP로 /mcp에 접속하고 content[0].text를 JSON으로 읽는다.
 */
public final class McpTestClient implements AutoCloseable {

	private static final JsonMapper JSON = JsonMapper.builder().build();

	private final McpSyncClient client;

	public McpTestClient(int port, String agentToken) {
		HttpRequest.Builder request = HttpRequest.newBuilder();
		if (agentToken != null) {
			request.header("Authorization", "Bearer " + agentToken);
		}
		HttpClientStreamableHttpTransport transport = HttpClientStreamableHttpTransport.builder("http://localhost:" + port)
			.endpoint("/mcp")
			.requestBuilder(request)
			.build();
		this.client = McpClient.sync(transport).requestTimeout(Duration.ofSeconds(30)).build();
		this.client.initialize();
	}

	/** 도구 응답. text는 content[0].text를 파싱한 JSON */
	public record Result(boolean isError, Map<String, Object> text) {

		@SuppressWarnings("unchecked")
		public Map<String, Object> error() {
			return (Map<String, Object>) this.text.get("error");
		}

	}

	@SuppressWarnings("unchecked")
	public Result call(String tool, Map<String, Object> arguments) {
		CallToolResult result = this.client.callTool(CallToolRequest.builder(tool).arguments(arguments).build());
		String text = ((TextContent) result.content().get(0)).text();
		return new Result(Boolean.TRUE.equals(result.isError()), JSON.readValue(text, Map.class));
	}

	/** Resource 원문. 권한이 없으면 McpError가 난다 */
	public String readResource(String uri) {
		var result = this.client.readResource(ReadResourceRequest.builder(uri).build());
		return ((TextResourceContents) result.contents().get(0)).text();
	}

	public List<String> resourceUris() {
		return this.client.listResources().resources().stream().map(resource -> resource.uri()).toList();
	}

	public List<String> toolNames() {
		return this.client.listTools().tools().stream().map(tool -> tool.name()).toList();
	}

	@Override
	public void close() {
		this.client.closeGracefully();
	}

}
