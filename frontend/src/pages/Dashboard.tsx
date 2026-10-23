import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Row, Col, Card, Statistic, Typography, List } from "antd";
import {
  BookOutlined,
  FileOutlined,
  MessageOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { getKnowledgeBases } from "../api/knowledgeBase";
import { getSessions } from "../api/chat";
import { useAuthStore } from "../store/authStore";

const { Title } = Typography;

export default function Dashboard() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const [kbCount, setKbCount] = useState(0);
  const [docCount] = useState(0);
  const [sessionCount, setSessionCount] = useState(0);
  const [recentSessions, setRecentSessions] = useState<any[]>([]);

  useEffect(() => {
    const fetch = async () => {
      try {
        const [kbRes, sessionRes] = await Promise.all([
          getKnowledgeBases(1, 1),
          getSessions(1, 5),
        ]);
        setKbCount(kbRes.data.data.total);
        setSessionCount(sessionRes.data.data.total);
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
            <Statistic title="知识库" value={kbCount} prefix={<BookOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="文档" value={docCount} prefix={<FileOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate("/chat")}>
            <Statistic title="对话" value={sessionCount} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate("/agent")}>
            <Statistic title="Agent" value="在线" prefix={<RobotOutlined />} />
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
