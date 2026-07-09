package com.scm.platform.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Application settings bound from the {@code scm.*} configuration namespace. */
@ConfigurationProperties(prefix = "scm")
public record ScmProperties(String serviceName, String version) {
}
