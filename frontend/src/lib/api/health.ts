import { apiGet } from "./client";
import type { HealthResponse } from "./types";

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/api/health", signal);
}
