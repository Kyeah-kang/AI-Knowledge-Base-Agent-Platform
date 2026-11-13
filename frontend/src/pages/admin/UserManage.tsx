import { useEffect, useState } from "react";
import { Table, Card, Typography, Tag, message, Switch } from "antd";
import { getUsers, toggleUserStatus } from "../../api/user";
import type { UserInfo } from "../../api/user";
import { DEFAULT_PAGE_SIZE } from "../../utils/constants";

const { Title } = Typography;

export default function UserManage() {
  const [data, setData] = useState<UserInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const fetchData = async (p = 1) => {
    setLoading(true);
    try {
      const res = await getUsers(p, DEFAULT_PAGE_SIZE);
      setData(res.data.data.items);
      setTotal(res.data.data.total);
      setPage(p);
    } catch { message.error("加载用户列表失败"); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  const handleToggleStatus = async (userId: number) => {
    try {
      const res = await toggleUserStatus(userId);
      message.success(`用户已${res.data.data.is_active ? "启用" : "禁用"}`);
      fetchData(page);
    } catch { message.error("操作失败"); }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 70 },
    { title: "用户名", dataIndex: "username", key: "username" },
    { title: "角色", dataIndex: "is_admin", key: "is_admin", width: 80, render: (v: boolean) => v ? <Tag color="red">管理员</Tag> : <Tag>用户</Tag> },
    { title: "状态", dataIndex: "is_active", key: "is_active", width: 100, render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "已激活" : "已禁用"}</Tag> },
    { title: "注册时间", dataIndex: "created_at", key: "created_at", width: 170, render: (t: string) => new Date(t).toLocaleString("zh-CN") },
    { title: "操作", key: "action", width: 100, render: (_: any, record: UserInfo) => (
      <Switch checked={record.is_active} onChange={() => handleToggleStatus(record.id)} checkedChildren="启用" unCheckedChildren="禁用" />
    )},
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>用户管理</Title>
      <Card>
        <Table dataSource={data} columns={columns} rowKey="id" loading={loading}
          pagination={{ current: page, total, pageSize: DEFAULT_PAGE_SIZE, onChange: fetchData, showTotal: (t) => `共 ${t} 个用户` }} />
      </Card>
    </div>
  );
}
