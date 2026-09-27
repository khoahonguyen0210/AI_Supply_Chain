import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "@/lib/api/client";
import { SessionProvider } from "@/lib/session";
import { errorResponse, stubBackend } from "@/test/render";
import { AppShell } from "./AppShell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const PROFILE = { userId: "pat", displayName: "Pat", role: "planner" };
const LOGIN = {
  accessToken: "signed.jwt.token",
  tokenType: "Bearer",
  expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  user: PROFILE,
};

function shell() {
  return render(
    <SessionProvider>
      <AppShell>
        <p>secret planning page</p>
      </AppShell>
    </SessionProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  setAccessToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppShell sign-in", () => {
  it("shows only the sign-in form, never the page, to someone who is not signed in", async () => {
    stubBackend({});
    shell();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("secret planning page")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
  });

  it("signs in, shows the page and the user's menu, and keeps the token for this tab only", async () => {
    const { calls } = stubBackend({ "/api/auth/login": LOGIN });
    shell();
    await userEvent.type(await screen.findByLabelText("User id"), " pat ");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("secret planning page")).toBeInTheDocument();
    expect(screen.getByText("Pat")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Monitoring" })).not.toBeInTheDocument();
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      userId: "pat",
      password: "a-long-password",
    });
    expect(window.sessionStorage.getItem("scm.session")).toContain("signed.jwt.token");
    expect(window.localStorage.getItem("scm.session")).toBeNull();
  });

  it("shows the Operations link only to administrators", async () => {
    stubBackend({
      "/api/auth/login": { ...LOGIN, user: { userId: "root", displayName: "Root", role: "admin" } },
    });
    shell();
    await userEvent.type(await screen.findByLabelText("User id"), "root");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("link", { name: "Monitoring" })).toBeInTheDocument();
  });

  it("gives the same message for a wrong password however it was wrong, and clears the password", async () => {
    stubBackend({
      "/api/auth/login": () => errorResponse(401, "INVALID_CREDENTIALS", "user id or password is wrong"),
    });
    shell();
    await userEvent.type(await screen.findByLabelText("User id"), "pat");
    await userEvent.type(screen.getByLabelText("Password"), "guess-guess-guess");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("The user id or password is wrong.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.queryByText("secret planning page")).not.toBeInTheDocument();
  });

  it("tells the person how long to wait when they are rate limited", async () => {
    stubBackend({
      "/api/auth/login": () =>
        errorResponse(429, "RATE_LIMITED", "too many requests; try again in 12 seconds"),
    });
    shell();
    await userEvent.type(await screen.findByLabelText("User id"), "pat");
    await userEvent.type(screen.getByLabelText("Password"), "guess-guess-guess");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/try again in 12 seconds/)).toBeInTheDocument();
  });

  it("resumes a stored session after checking it with the backend", async () => {
    window.sessionStorage.setItem(
      "scm.session",
      JSON.stringify({ token: LOGIN.accessToken, expiresAt: LOGIN.expiresAt }),
    );
    const { calls } = stubBackend({ "/api/auth/me": PROFILE });
    shell();
    expect(await screen.findByText("secret planning page")).toBeInTheDocument();
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe(
      "Bearer signed.jwt.token",
    );
  });

  it("ignores a stored session that has expired", async () => {
    window.sessionStorage.setItem(
      "scm.session",
      JSON.stringify({ token: "old", expiresAt: new Date(Date.now() - 1000).toISOString() }),
    );
    const { calls } = stubBackend({});
    shell();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("drops a stored session the backend no longer accepts", async () => {
    window.sessionStorage.setItem(
      "scm.session",
      JSON.stringify({ token: LOGIN.accessToken, expiresAt: LOGIN.expiresAt }),
    );
    stubBackend({ "/api/auth/me": () => errorResponse(401, "UNAUTHENTICATED", "no") });
    shell();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("scm.session")).toBeNull();
  });

  it("signs out: the page disappears and the token is forgotten", async () => {
    stubBackend({ "/api/auth/login": LOGIN });
    shell();
    await userEvent.type(await screen.findByLabelText("User id"), "pat");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("secret planning page");

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.queryByText("secret planning page")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("scm.session")).toBeNull();
  });
});
