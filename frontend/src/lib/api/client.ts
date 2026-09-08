import type { ApiErrorBody } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly body?: ApiErrorBody,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "message" in value &&
    "status" in value
  );
}

export interface RequestOptions {
  signal?: AbortSignal;
  /** Sent as Idempotency-Key so a retry is not queued twice. */
  idempotencyKey?: string;
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body: unknown,
  options: RequestOptions,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("Backend is unreachable", 0, "NETWORK_ERROR");
  }

  if (!response.ok) {
    // A 401 on a call that carried a token means the session is over; a failed login is just an error.
    if (response.status === 401 && accessToken) onUnauthorized?.();
    const errorBody: unknown = await response.json().catch(() => undefined);
    if (isApiErrorBody(errorBody)) {
      throw new ApiError(errorBody.message, errorBody.status, errorBody.code, errorBody);
    }
    throw new ApiError(response.statusText || "Request failed", response.status, "HTTP_ERROR");
  }

  return (await response.json()) as T;
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>("GET", path, undefined, { signal });
}

export function apiPost<T>(path: string, body: unknown, options: RequestOptions = {}): Promise<T> {
  return request<T>("POST", path, body, options);
}

export function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Unexpected error";
}
