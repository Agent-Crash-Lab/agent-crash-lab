package com.agentcrashlab.mcp.tool;

import java.util.Map;
import java.util.Set;

import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;

/**
 * 도구 인자 검사. drafts input_schema가 additionalProperties: false라서 키 집합이 정확히 같아야 한다.
 */
public final class ToolArgs {

	private ToolArgs() {
	}

	public static void requireKeys(Map<String, Object> arguments, Set<String> keys) {
		if (!arguments.keySet().equals(keys)) {
			throw new ToolException(ToolErrorCode.VALIDATION_ERROR);
		}
	}

	public static String text(Map<String, Object> arguments, String key) {
		if (arguments.get(key) instanceof String value && !value.isBlank()) {
			return value;
		}
		throw new ToolException(ToolErrorCode.VALIDATION_ERROR);
	}

}
