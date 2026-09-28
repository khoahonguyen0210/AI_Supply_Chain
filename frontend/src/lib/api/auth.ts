import { apiGet, apiPost } from "./client";

export interface Profile {
  userId: string;
  displayName: string;
  role: string;
}

export interface LoginResponse {
  accessToken: string;
  tokenType: string;
  expiresAt: string;
  user: Profile;
}

export const login = (userId: string, password: string) =>
  apiPost<LoginResponse>("/api/auth/login", { userId, password });

export const register = (userId: string, displayName: string, password: string) =>
  apiPost<LoginResponse>("/api/auth/register", { userId, displayName, password });

export const getMe = (signal?: AbortSignal) => apiGet<Profile>("/api/auth/me", signal);
