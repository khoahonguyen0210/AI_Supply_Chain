"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Notice } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/session";

/** What to tell the person who could not sign in, without hinting at which part was wrong. */
export function loginMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "RATE_LIMITED") return error.message;
    if (error.code === "INVALID_CREDENTIALS") return "The user id or password is wrong.";
    if (error.code === "NETWORK_ERROR") return "The server cannot be reached. Try again in a moment.";
  }
  return "Sign-in failed. Try again.";
}

export function LoginForm() {
  const { signIn } = useAuth();
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(userId, password);
    } catch (failure) {
      setError(loginMessage(failure));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel login-panel" aria-labelledby="login-heading">
      <h1 id="login-heading">Sign in</h1>
      <p className="muted">Use the account your administrator created for you.</p>
      <form className="stack" onSubmit={submit}>
        <label className="field">
          <span>User id</span>
          <input
            value={userId}
            autoComplete="username"
            onChange={(e) => setUserId(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <button type="submit" className="primary" disabled={busy || !userId || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error ? <Notice tone="bad">{error}</Notice> : null}
      </form>
    </section>
  );
}
