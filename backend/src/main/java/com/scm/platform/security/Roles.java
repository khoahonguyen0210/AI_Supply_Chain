package com.scm.platform.security;

import com.scm.platform.error.ApiException;
import java.util.Set;

public final class Roles {

	public static final String PLANNER = "planner";

	public static final String PROCUREMENT_MANAGER = "procurement_manager";

	public static final String FINANCE = "finance";

	public static final String ADMIN = "admin";

	public static final Set<String> PLANNING = Set.of(PLANNER, PROCUREMENT_MANAGER, ADMIN);

	private Roles() {
	}

	public static void require(Actor actor, Set<String> allowed) {
		if (!allowed.contains(actor.role())) {
			throw ApiException.forbidden("role " + actor.role() + " may not do this");
		}
	}

}
