// Auth API

import client from "./client";

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  email?: string;
}

export interface TokenData {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: {
    id: number;
    username: string;
    email: string;
    is_admin: boolean;
  };
}

export const login = (data: LoginRequest) =>
  client.post<{ code: number; message: string; data: TokenData }>("/auth/login", data);

export const register = (data: RegisterRequest) =>
  client.post<{ code: number; message: string; data: TokenData }>("/auth/register", data);

export const refreshToken = (refresh_token: string) =>
  client.post<{ code: number; message: string; data: { access_token: string } }>("/auth/refresh", { refresh_token });
