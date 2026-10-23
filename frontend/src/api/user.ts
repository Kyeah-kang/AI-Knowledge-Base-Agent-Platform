// User API

import client from "./client";

export interface UserInfo {
  id: number;
  username: string;
  email: string;
  avatar: string | null;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
}

export const getProfile = () =>
  client.get<{ code: number; data: UserInfo }>("/users/me");

export const updateProfile = (data: { username?: string; email?: string }) =>
  client.put<{ code: number; data: UserInfo }>("/users/me", data);

export const getUsers = (page = 1, pageSize = 20) =>
  client.get<{ code: number; data: { items: UserInfo[]; total: number; page: number; page_size: number } }>(
    `/users?page=${page}&page_size=${pageSize}`
  );

export const toggleUserStatus = (userId: number) =>
  client.put<{ code: number; data: UserInfo }>(`/users/${userId}/status`);
