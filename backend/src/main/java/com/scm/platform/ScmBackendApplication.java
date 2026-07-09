package com.scm.platform;

import com.scm.platform.config.ScmProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(ScmProperties.class)
public class ScmBackendApplication {

	public static void main(String[] args) {
		SpringApplication.run(ScmBackendApplication.class, args);
	}

}
