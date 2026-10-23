// 管理员守卫 — 非管理员跳转到首页

import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

export default function AdminRoute() {
  const isAdmin = useAuthStore((s) => s.isAdmin);
  return isAdmin ? <Outlet /> : <Navigate to="/dashboard" replace />;
}
