import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiGet,
  apiPost,
  query,
  setAccessToken,
  setUnauthorizedHandler,
} from "./client";

const fetchMock = vi.fn();

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  setAccessToken(null);
  setUnauthorizedHandler(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("sends the access token as a bearer credential on every request", async () => {
    fetchMock.mockResolvedValue(reply(200, { ok: true }));
    setAccessToken("abc.def.ghi");
    await apiGet("/api/skus");
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer abc.def.ghi");
  });

  it("sends no credentials when nobody is signed in", async () => {
    fetchMock.mockResolvedValue(reply(200, {}));
    await apiGet("/api/skus");
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("ends the session when the backend rejects the token", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setAccessToken("expired");
    fetchMock.mockResolvedValue(reply(401, { status: 401, code: "UNAUTHENTICATED", message: "no" }));
    await expect(apiGet("/api/skus")).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("does not treat a failed sign-in as an expired session", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValue(
      reply(401, { status: 401, code: "INVALID_CREDENTIALS", message: "wrong" }),
    );
    await expect(apiPost("/api/auth/login", {})).rejects.toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("posts JSON with an optional idempotency key", async () => {
    fetchMock.mockResolvedValue(reply(202, { id: "1" }));
    await apiPost("/api/jobs", { type: "FORECAST" }, { idempotencyKey: "abc" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/jobs");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ type: "FORECAST" }));
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers["Idempotency-Key"]).toBe("abc");
  });

  it("turns the backend's error body into an ApiError with its code", async () => {
    fetchMock.mockResolvedValue(
      reply(404, {
        timestamp: "t",
        status: 404,
        code: "UNKNOWN_SKU",
        message: "no SKU X",
        path: "/api/demand",
        violations: [],
      }),
    );
    await expect(apiGet("/api/demand")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "UNKNOWN_SKU",
      message: "no SKU X",
    });
  });

  it("falls back to a generic error when the body is not the error contract", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 502, statusText: "Bad Gateway" }));
    await expect(apiGet("/api/x")).rejects.toMatchObject({ code: "HTTP_ERROR", status: 502 });
  });

  it("reports an unreachable backend", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const error = await apiGet("/api/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("NETWORK_ERROR");
  });

  it("lets aborts through untouched", async () => {
    fetchMock.mockRejectedValue(new DOMException("Aborted", "AbortError"));
    await expect(apiGet("/api/x")).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("query", () => {
  it("keeps defined values and drops empty ones", () => {
    expect(query({ a: 1, b: undefined, c: "", d: "x y", e: false })).toBe("?a=1&d=x+y&e=false");
    expect(query({})).toBe("");
  });
});
