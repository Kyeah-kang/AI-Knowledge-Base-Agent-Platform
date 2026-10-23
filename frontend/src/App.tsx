// 应用入口

import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";

import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import AdminRoute from "./components/AdminRoute";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";
import AgentChat from "./pages/AgentChat";
import KnowledgeBaseList from "./pages/KnowledgeBaseList";
import DocumentList from "./pages/DocumentList";
import Profile from "./pages/Profile";
import UserManage from "./pages/admin/UserManage";
import ToolManage from "./pages/admin/ToolManage";
import { useAuthStore } from "./store/authStore";

function App() {
  const init = useAuthStore((s) => s.init);

  useEffect(() => {
    init(); // 从 localStorage 恢复登录态
  }, []);

  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          {/* 公开路由 */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* 需要登录的路由 */}
          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/agent" element={<AgentChat />} />
              <Route path="/knowledge-bases" element={<KnowledgeBaseList />} />
              <Route path="/knowledge-bases/:kbId/documents" element={<DocumentList />} />
              <Route path="/profile" element={<Profile />} />

              {/* 管理员路由 */}
              <Route element={<AdminRoute />}>
                <Route path="/admin/users" element={<UserManage />} />
                <Route path="/admin/tools" element={<ToolManage />} />
                <Route
                  path="/admin"
                  element={<Navigate to="/admin/users" replace />}
                />
              </Route>

              {/* 默认重定向 */}
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}

export default App;
