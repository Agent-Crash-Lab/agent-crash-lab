package com.agentcrashlab.mcp.auth;

import java.util.List;

public record CurrentUser(String userId, List<String> roles, String purchasingOrgId) {

	public static final String REQUESTER = "REQUESTER";

	public static final String APPROVER = "APPROVER";

	public boolean hasRole(String role) {
		return this.roles.contains(role);
	}

}
