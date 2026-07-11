package com.scm.platform;

import com.scm.platform.support.PostgresContainerConfig;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

@SpringBootTest
@Import(PostgresContainerConfig.class)
class ScmBackendApplicationTests {

	@Test
	void contextLoads() {
	}

}
