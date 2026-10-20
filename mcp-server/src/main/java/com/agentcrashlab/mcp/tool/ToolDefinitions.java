package com.agentcrashlab.mcp.tool;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

import io.modelcontextprotocol.spec.McpSchema.Tool;
import org.springframework.core.io.ClassPathResource;

import tools.jackson.databind.json.JsonMapper;

/**
 * 리소스의 도구 정의(drafts 복사본)에서 MCP Tool을 만든다. 설명과 입력 스키마는 원본 그대로 쓴다.
 */
public final class ToolDefinitions {

	private final Map<String, Map<String, Object>> byName;

	private ToolDefinitions(Map<String, Map<String, Object>> byName) {
		this.byName = byName;
	}

	@SuppressWarnings("unchecked")
	public static ToolDefinitions load(JsonMapper json, String resource) {
		try (InputStream in = new ClassPathResource(resource).getInputStream()) {
			Map<String, Object> file = json.readValue(in, Map.class);
			List<Map<String, Object>> tools = (List<Map<String, Object>>) file.get("tools");
			Map<String, Map<String, Object>> byName = new java.util.LinkedHashMap<>();
			tools.forEach(tool -> byName.put((String) tool.get("name"), tool));
			return new ToolDefinitions(byName);
		}
		catch (IOException ex) {
			throw new IllegalStateException("Cannot read tool definitions: " + resource, ex);
		}
	}

	@SuppressWarnings("unchecked")
	public Tool tool(String name) {
		Map<String, Object> definition = this.byName.get(name);
		if (definition == null) {
			throw new IllegalArgumentException("Unknown tool: " + name);
		}
		return Tool.builder(name, (Map<String, Object>) definition.get("input_schema"))
			.description((String) definition.get("description"))
			.build();
	}

}
