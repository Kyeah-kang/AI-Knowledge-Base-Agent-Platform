// Axios 实例 — 自动携带 Token + 自动刷新

import axios from "axios";
import { getAccessToken, getRefreshToken, setAccessToken, clearAuth } from "../utils/token";

/**
 * 后端 API 前缀（唯一来源）。
 *
 * 两种部署形态都兼容：
 *   - 本机开发：`.env` 里写 http://localhost:8000/api/v1
 *   - 容器/生产：构建时传 VITE_API_BASE_URL=/api/v1，由 nginx 同源反代（无 CORS）
 *
 * 默认值刻意用相对路径 `/api/v1`：同源部署时不需要配置任何环境变量。
 */
export const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "/api/v1";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// 请求拦截器：自动带 Token
client.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：401 时自动用 refresh_token 刷新
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes("/auth/refresh")
    ) {
      originalRequest._retry = true;
      const refreshToken = getRefreshToken();
      if (refreshToken) {
        try {
          const res = await axios.post(`${API_BASE}/auth/refresh`, {
            refresh_token: refreshToken,
          });
          const newToken = res.data.data?.access_token;
          if (newToken) {
            setAccessToken(newToken);
            originalRequest.headers.Authorization = `Bearer ${newToken}`;
            return client(originalRequest);
          }
        } catch {
          clearAuth();
          window.location.href = "/login";
        }
      } else {
        clearAuth();
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default client;
