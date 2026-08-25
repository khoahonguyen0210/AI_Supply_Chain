package com.scm.platform;

import com.scm.platform.config.ScmProperties;
import com.scm.platform.security.SecurityProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableConfigurationProperties({ ScmProperties.class, SecurityProperties.class })
@EnableScheduling
public class ScmBackendApplication {

	public static void main(String[] args) {
		SpringApplication.run(ScmBackendApplication.class, args);
	}

}
