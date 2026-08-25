package com.scm.platform.security;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Component
public class UserBootstrap implements ApplicationRunner {

	private static final Logger log = LoggerFactory.getLogger(UserBootstrap.class);

	private final UserService users;

	private final SecurityProperties properties;

	public UserBootstrap(UserService users, SecurityProperties properties) {
		this.users = users;
		this.properties = properties;
	}

	@Override
	public void run(ApplicationArguments args) {
		properties.bootstrapUsers().forEach(users::createOrRefresh);
		log.info("{} bootstrap user(s) are in place", properties.bootstrapUsers().size());
	}

}
