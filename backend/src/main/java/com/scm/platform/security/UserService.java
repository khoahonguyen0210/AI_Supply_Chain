package com.scm.platform.security;

import com.scm.platform.security.UserRepository.UserRow;
import java.util.Optional;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class UserService {

	private final UserRepository users;

	private final PasswordEncoder passwords;

	/** Checked for unknown users too, so they take as long to reject as a wrong password. */
	private final String decoyHash;

	public UserService(UserRepository users, PasswordEncoder passwords) {
		this.users = users;
		this.passwords = passwords;
		this.decoyHash = passwords.encode("decoy-password-for-timing");
	}

	/** Empty for any failure, whatever the reason. */
	public Optional<UserRow> authenticate(String userId, String password) {
		Optional<UserRow> user = users.find(userId == null ? "" : userId);
		String hash = user.map(UserRow::passwordHash).orElse(decoyHash);
		boolean matches = !SecurityProperties.passwordTooLong(password)
				&& passwords.matches(password == null ? "" : password, hash);
		if (user.isPresent() && matches && user.get().active()) {
			users.recordLogin(userId);
			return user;
		}
		return Optional.empty();
	}

	/** Self sign-up is always the planner role, so nobody grants themselves approval rights. */
	public Optional<UserRow> register(String userId, String displayName, String password) {
		String hash = passwords.encode(password);
		if (!users.insertNew(userId, displayName, Roles.PLANNER, hash)) {
			return Optional.empty();
		}
		return users.find(userId);
	}

	public void createOrRefresh(SecurityProperties.BootstrapUser user) {
		users.upsert(user.userId(), user.displayName() == null || user.displayName().isBlank() ? user.userId()
				: user.displayName(), user.role(), passwords.encode(user.password()));
	}

}
