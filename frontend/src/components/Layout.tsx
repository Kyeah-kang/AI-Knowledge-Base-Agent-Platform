import { useState } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { Layout as AntLayout, Menu, Button, Dropdown, Avatar } from "antd";
import {
  DashboardOutlined,
  MessageOutlined,
  RobotOutlined,
  BookOutlined,
  UserOutlined,
  SettingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import { useAuthStore } from "../store/authStore";
import { APP_NAME } from "../utils/constants";

const { Header, Sider, Content } = AntLayout;

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, isAdmin, logout } = useAuthStore();

  // 根据权限过滤菜单
  const menuItems = [
    { key: "/dashboard", icon: <DashboardOutlined />, label: "仪表盘" },
    { key: "/chat", icon: <MessageOutlined />, label: "智能对话" },
    { key: "/agent", icon: <RobotOutlined />, label: "Agent 对话" },
    { key: "/knowledge-bases", icon: <BookOutlined />, label: "知识库管理" },
    { key: "/profile", icon: <UserOutlined />, label: "个人中心" },
    ...(isAdmin ? [{ key: "/admin", icon: <SettingOutlined />, label: "管理后台" }] : []),
  ];

  const selectedKey = "/" + location.pathname.split("/")[1];

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const dropdownItems = [
    { key: "profile", icon: <UserOutlined />, label: "个人中心", onClick: () => navigate("/profile") },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: handleLogout },
  ];

  return (
    <AntLayout style={{ minHeight: "100vh" }}>
      <Sider trigger={null} collapsible collapsed={collapsed} theme="dark">
        <div style={{ height: 64, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: collapsed ? 14 : 18, fontWeight: "bold" }}>
          {collapsed ? "AI" : APP_NAME}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <AntLayout>
        <Header
          style={{
            padding: "0 24px",
            background: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
          />
          <Dropdown menu={{ items: dropdownItems }} placement="bottomRight">
            <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
              <Avatar icon={<UserOutlined />} />
              <span>{user?.username || "用户"}</span>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ margin: 16, minHeight: 280 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
