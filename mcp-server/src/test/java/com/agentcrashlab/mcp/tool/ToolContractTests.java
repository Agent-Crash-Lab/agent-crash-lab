package com.agentcrashlab.mcp.tool;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import tools.jackson.databind.json.JsonMapper;

/**
 * 서버에 복사해 둔 도구 정의가 drafts 원본과 같은지 확인한다. 원본이 바뀌면 이 테스트가 실패한다.
 */
class ToolContractTests {

	static final JsonMapper JSON = JsonMapper.builder().build();

	@Test
	void businessToolsMatchDraftContract() throws IOException {
		assertSameTools("mcp/business-tools.json", "../qa/examples/purchase-tools.json");
	}

	@Test
	void ragToolsMatchDraftContract() throws IOException {
		assertSameTools("mcp/rag-tools.json", "../qa/contracts/investigation-tools.json");
	}

	@SuppressWarnings("unchecked")
	static void assertSameTools(String resource, String draft) throws IOException {
		List<Map<String, Object>> copy = (List<Map<String, Object>>) JSON
			.readValue(new ClassPathResource(resource).getInputStream(), Map.class)
			.get("tools");
		List<Map<String, Object>> original = (List<Map<String, Object>>) JSON
			.readValue(Files.readString(Path.of(draft)), Map.class)
			.get("tools");

		assertThat(copy).hasSameSizeAs(original);
		for (int i = 0; i < original.size(); i++) {
			assertThat(copy.get(i).get("name")).isEqualTo(original.get(i).get("name"));
			// investigation-tools.json에는 설명이 없어서, 원본에 설명이 있을 때만 비교한다
			if (original.get(i).containsKey("description")) {
				assertThat(copy.get(i).get("description")).isEqualTo(original.get(i).get("description"));
			}
			assertThat(copy.get(i).get("input_schema")).isEqualTo(original.get(i).get("input_schema"));
		}
	}

}
