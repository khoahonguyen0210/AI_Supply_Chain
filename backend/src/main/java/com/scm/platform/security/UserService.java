package com.scm.platform.security;

import com.scm.platform.security.UserRepository.UserRow;
import java.util.Optional;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class UserService {

	private final UserRepository users;

	private final PasswordEncoder passwords;

	/** Checked when the user does not exist, so an unknown user takes as long to reject as a wrong password. */
	private final String decoyHash;

	public UserService(UserRepository users, PasswordEncoder passwords) {
		this.users = users;
		this.passwords = passwords;
		this.decoyHash = passwords.encode("decoy-password-for-timing");
	}

	/** The user if the credentials are right and the account is active; otherwise empty, whatever the reason. */
	public Optional<UserRow> authenticate(String userId, String password) {
		Optional<UserRow> user = users.find(userId == null ? "" : userId);
		String hash = user.map(UserRow::passwordHash).orElse(decoyHash);
		boolean matches = passwords.matches(password == null ? "" : password, hash);
		if (user.isPresent() && matches && user.get().active()) {
			users.recordLogin(userId);
			return user;
		}
		return Optional.empty();
	}

	public void createOrRefresh(SecurityProperties.BootstrapUser user) {
		users.upsert(user.userId(), user.displayName() == null || user.displayName().isBlank() ? user.userId()
				: user.displayName(), user.role(), passwords.encode(user.password()));
	}

}
