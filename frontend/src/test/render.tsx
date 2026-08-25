import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import type { Profile } from "@/lib/api/auth";
import { setAccessToken } from "@/lib/api/client";
import { SessionProvider } from "@/lib/session";

export const TEST_TOKEN = "test-access-token";

export const PLANNER: Profile = { userId: "pat", displayName: "Pat", role: "planner" };

/** Renders the page as a signed-in user (a planner unless told otherwise), with a token on every request. */
export function renderWithSession(ui: ReactElement, user: Profile = PLANNER) {
  setAccessToken(TEST_TOKEN);
  return render(<SessionProvider initialUser={user}>{ui}</SessionProvider>);
}

type Handler = (url: string, init: RequestInit) => unknown;

/**
 * Stubs `fetch` with a router: the first route whose path prefix matches answers. A handler may return a
 * value (sent as 200 JSON) or a Response. Unmatched requests fail the test loudly.
 */
export function stubBackend(routes: Record<string, Handler | unknown>) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({ url, init });
    const match = Object.keys(routes).find((prefix) => url.startsWith(prefix));
    if (!match) throw new Error(`unexpected request: ${init.method ?? "GET"} ${url}`);
    const route = routes[match];
    const value = typeof route === "function" ? (route as Handler)(url, init) : route;
    if (value instanceof Response) return value;
    return new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function errorResponse(status: number, code: string, message: string): Response {
  return new Response(
    JSON.stringify({ timestamp: "t", status, code, message, path: "/", violations: [] }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}
