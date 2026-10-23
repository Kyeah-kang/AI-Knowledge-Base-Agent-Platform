import { useEffect, useState } from "react";
import { Table, Card, Typography, Tag, message, Switch } from "antd";
import { getAgentTools, toggleAgentTool } from "../../api/agent";
import type { AgentTool } from "../../api/agent";

const { Title } = Typography;

export default function ToolManage() {
  const [data, setData] = useState<AgentTool[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await getAgentTools(false);
      setData(res.data.data);
    } catch { message.error("加载工具列表失败"); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  const handleToggle = async (toolId: number) => {
    try { await toggleAgentTool(toolId); message.success("状态已更新"); fetchData(); }
    catch { message.error("操作失败"); }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "名称", dataIndex: "name", key: "name", width: 150 },
    { title: "展示名", dataIndex: "display_name", key: "display_name", width: 120 },
    { title: "描述", dataIndex: "description", key: "description", ellipsis: true },
    { title: "状态", dataIndex: "enabled", key: "enabled", width: 80, render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "启用" : "禁用"}</Tag> },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 170, render: (t: string) => new Date(t).toLocaleString("zh-CN") },
    { title: "操作", key: "action", width: 100, render: (_: any, record: AgentTool) => (
      <Switch checked={record.enabled} onChange={() => handleToggle(record.id)} checkedChildren="启用" unCheckedChildren="禁用" />
    )},
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>Agent 工具管理</Title>
      <Card>
        <Table dataSource={data} columns={columns} rowKey="id" loading={loading} pagination={false} />
      </Card>
    </div>
  );
}
