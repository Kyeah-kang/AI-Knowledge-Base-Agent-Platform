import { useEffect, useState } from "react";
import { Table, Card, Typography, Tag, message, Switch, Tooltip, Alert } from "antd";
import { getAgentTools, toggleAgentTool } from "../../api/agent";
import type { AgentTool } from "../../api/agent";

const { Title } = Typography;

// 后端真正实现了 executor 的工具（见 app/agent/tools.py::_TOOL_EXECUTORS）。
// 数据库里新增的工具目前只存 schema，没有实现，因此不会暴露给 LLM（P1-7）。
const EXECUTABLE_TOOLS = new Set(["web_search", "calculator", "knowledge_retrieval"]);

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
    {
      title: "可执行", key: "executable", width: 110,
      render: (_: any, record: AgentTool) => (
        EXECUTABLE_TOOLS.has(record.name) ? (
          <Tag color="blue">已实现</Tag>
        ) : (
          <Tooltip title="只有 schema、没有 executor 实现：不会交给 LLM 调用，仅在此处展示">
            <Tag color="orange">仅展示</Tag>
          </Tooltip>
        )
      ),
    },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 170, render: (t: string) => new Date(t).toLocaleString("zh-CN") },
    { title: "操作", key: "action", width: 100, render: (_: any, record: AgentTool) => (
      <Switch checked={record.enabled} onChange={() => handleToggle(record.id)} checkedChildren="启用" unCheckedChildren="禁用" />
    )},
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>Agent 工具管理</Title>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="工具执行需要后端 executor 实现"
        description="标记为“仅展示”的工具只有 JSON Schema，没有对应实现，因此不会出现在 LLM 的工具列表里（避免模型调到一个必然失败的工具）。新增可执行工具需要先在 app/agent/tools.py 的 _TOOL_EXECUTORS 中登记实现。"
      />
      <Card>
        <Table dataSource={data} columns={columns} rowKey="id" loading={loading} pagination={false} />
      </Card>
    </div>
  );
}
