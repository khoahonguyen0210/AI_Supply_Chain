package com.scm.platform.security;

import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class UserRepository {

	public record UserRow(String userId, String displayName, String role, String passwordHash, boolean active) {
	}

	private final JdbcClient jdbc;

	public UserRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	public Optional<UserRow> find(String userId) {
		return jdbc.sql("SELECT user_id, display_name, role, password_hash, active FROM app_user"
				+ " WHERE user_id = :id").param("id", userId)
				.query((rs, i) -> new UserRow(rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4),
						rs.getBoolean(5)))
				.optional();
	}

	public void upsert(String userId, String displayName, String role, String passwordHash) {
		jdbc.sql("""
				INSERT INTO app_user (user_id, display_name, role, password_hash) VALUES (:id, :name, :role, :hash)
				ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name, role = EXCLUDED.role,
				    password_hash = EXCLUDED.password_hash, active = true""")
				.param("id", userId).param("name", displayName).param("role", role).param("hash", passwordHash)
				.update();
	}

	/** False if the user id is taken, ignoring case. */
	public boolean insertNew(String userId, String displayName, String role, String passwordHash) {
		return jdbc.sql("""
				INSERT INTO app_user (user_id, display_name, role, password_hash)
				SELECT :id, :name, :role, :hash
				WHERE NOT EXISTS (SELECT 1 FROM app_user WHERE lower(user_id) = lower(:id))
				ON CONFLICT (user_id) DO NOTHING""")
				.param("id", userId).param("name", displayName).param("role", role).param("hash", passwordHash)
				.update() == 1;
	}

	public void recordLogin(String userId) {
		jdbc.sql("UPDATE app_user SET last_login_at = now() WHERE user_id = :id").param("id", userId).update();
	}

}
