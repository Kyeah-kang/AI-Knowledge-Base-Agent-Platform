import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Row, Col, Card, Statistic, Typography, List } from "antd";
import {
  BookOutlined,
  FileOutlined,
  MessageOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { getSessions } from "../api/chat";
import { getOverview } from "../api/stats";
import type { StatsOverview } from "../api/stats";
import { useAuthStore } from "../store/authStore";

const { Title, Text } = Typography;

export default function Dashboard() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  // P2-9：这些数字原来要么恒为 0、要么靠列表接口反推。
  // 现在统一来自 /stats/overview（后端按当前用户统计）。
  const [stats, setStats] = useState<StatsOverview>({
    kb_count: 0,
    doc_count: 0,
    failed_doc_count: 0,
    session_count: 0,
    message_count: 0,
  });
  const [recentSessions, setRecentSessions] = useState<any[]>([]);

  useEffect(() => {
    const fetch = async () => {
      try {
        const [statsRes, sessionRes] = await Promise.all([
          getOverview(),
          getSessions(1, 5),
        ]);
        setStats(statsRes.data.data);
        setRecentSessions(sessionRes.data.data.items);
      } catch {}
    };
    fetch();
  }, []);

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>
        欢迎回来，{user?.username || "用户"}
      </Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate("/knowledge-bases")}>
            <Statistic title="知识库" value={stats.kb_count} prefix={<BookOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate("/knowledge-bases")}>
            <Statistic title="文档" value={stats.doc_count} prefix={<FileOutlined />} />
            {stats.failed_doc_count > 0 && (
              <Text type="danger" style={{ fontSize: 12 }}>
                {stats.failed_doc_count} 条处理失败
              </Text>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate("/chat")}>
            <Statistic
              title="对话"
              value={stats.session_count}
              prefix={<MessageOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate("/agent")}>
            <Statistic
              title="消息"
              value={stats.message_count}
              prefix={<RobotOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title="最近对话" style={{ marginTop: 24 }}>
        <List
          dataSource={recentSessions}
          renderItem={(item: any) => (
            <List.Item
              style={{ cursor: "pointer" }}
              onClick={() => navigate(`/chat?session_id=${item.id}`)}
            >
              <List.Item.Meta
                avatar={<MessageOutlined />}
                title={item.title}
                description={`${item.message_count} 条消息 · ${new Date(item.updated_at).toLocaleString("zh-CN")}`}
              />
            </List.Item>
          )}
          locale={{ emptyText: "暂无对话" }}
        />
      </Card>
    </div>
  );
}
