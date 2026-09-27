"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getMe, login } from "./api/auth";
import type { Profile } from "./api/auth";
import { setAccessToken, setUnauthorizedHandler } from "./api/client";

const STORAGE_KEY = "scm.session";

interface Stored {
  token: string;
  expiresAt: string;
}

interface AuthValue {
  /** The signed-in user, or null when nobody is. */
  user: Profile | null;
  /** False until a stored session has been checked with the backend, so nothing fetches too early. */
  ready: boolean;
  signIn: (userId: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

function readStored(): Stored | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as Stored;
    return new Date(stored.expiresAt).getTime() > Date.now() ? stored : null;
  } catch {
    return null;
  }
}

function writeStored(value: Stored | null): void {
  try {
    if (value) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // the session then lasts only until the page is reloaded
  }
}

/** Signed-in user; the token lives in sessionStorage, so it ends with the tab. */
export function SessionProvider({
  children,
  initialUser,
}: {
  children: ReactNode;
  initialUser?: Profile;
}) {
  const [user, setUser] = useState<Profile | null>(initialUser ?? null);
  const [ready, setReady] = useState(initialUser !== undefined);

  const signOut = useCallback(() => {
    setAccessToken(null);
    writeStored(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  useEffect(() => {
    if (initialUser !== undefined) return;
    const stored = readStored();
    if (!stored) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sessionStorage is only readable after mount
      setReady(true);
      return;
    }
    setAccessToken(stored.token);
    getMe()
      .then(setUser)
      .catch(() => {
        setAccessToken(null);
        writeStored(null);
      })
      .finally(() => setReady(true));
  }, [initialUser]);

  const signIn = useCallback(async (userId: string, password: string) => {
    const response = await login(userId.trim(), password);
    setAccessToken(response.accessToken);
    writeStored({ token: response.accessToken, expiresAt: response.expiresAt });
    setUser(response.user);
  }, []);

  const value = useMemo(() => ({ user, ready, signIn, signOut }), [user, ready, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** The sign-in state, for the shell and the login page. */
export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside SessionProvider");
  return value;
}

/** The signed-in user, for pages. They are only rendered once someone is signed in. */
export function useSession(): { user: Profile; ready: true } {
  const { user } = useAuth();
  if (!user) throw new Error("useSession needs a signed-in user");
  return { user, ready: true };
}
