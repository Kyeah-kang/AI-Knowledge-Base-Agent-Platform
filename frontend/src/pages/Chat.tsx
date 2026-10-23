// 智能对话页面 — SSE 流式输出 + 知识库选择

import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Input, Button, Card, List, Select, Space, Typography, message, Spin,
} from "antd";
import { SendOutlined, PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import {
  getSessions, createSession, getSessionDetail, deleteSession,
} from "../api/chat";
import { getKnowledgeBases } from "../api/knowledgeBase";
import type { ChatSession } from "../api/chat";
import { useChatStore } from "../store/chatStore";
import { useSSE } from "../hooks/useSSE";

const { TextArea } = Input;
const { Text } = Typography;

export default function Chat() {
  const [searchParams] = useSearchParams();

  const {
    sessions, currentSessionId, messages, isStreaming,
    setSessions, setCurrentSession, setMessages, addMessage,
    setIsStreaming, appendToLastMessage, reset,
  } = useChatStore();

  const [input, setInput] = useState("");
  const [kbOptions, setKbOptions] = useState<{ label: string; value: number }[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { connect } = useSSE();

  // 加载会话列表 + 知识库列表
  useEffect(() => {
    const init = async () => {
      setSessionsLoading(true);
      try {
        const [sessionRes, kbRes] = await Promise.all([
          getSessions(1, 50),
          getKnowledgeBases(1, 50),
        ]);
        setSessions(sessionRes.data.data.items);
        setKbOptions(
          kbRes.data.data.items.map((kb) => ({
            label: kb.name,
            value: kb.id,
          }))
        );
      } catch {
        message.error("加载数据失败");
      } finally {
        setSessionsLoading(false);
      }
    };
    init();
    reset();
  }, []);

  // URL 参数指定 session_id 时自动加载
  useEffect(() => {
    const sid = searchParams.get("session_id");
    if (sid) {
      loadSession(Number(sid));
    }
  }, [searchParams]);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const loadSession = async (sessionId: number) => {
    setLoading(true);
    try {
      const res = await getSessionDetail(sessionId);
      setCurrentSession(sessionId);
      setMessages(res.data.data.messages);
    } catch {
      message.error("加载会话失败");
    } finally {
      setLoading(false);
    }
  };

  const handleNewSession = async () => {
    try {
      const res = await createSession("新对话");
      setSessions([res.data.data, ...sessions]);
      setCurrentSession(res.data.data.id);
      setMessages([]);
    } catch {
      message.error("创建会话失败");
    }
  };

  const handleDeleteSession = async (sessionId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteSession(sessionId);
      setSessions(sessions.filter((s) => s.id !== sessionId));
      if (currentSessionId === sessionId) {
        setCurrentSession(0);
        setMessages([]);
      }
    } catch {
      message.error("删除失败");
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;
    if (!currentSessionId) {
      message.warning("请先选择或创建一个会话");
      return;
    }

    const userContent = input.trim();
    setInput("");

    addMessage({ id: Date.now(), session_id: currentSessionId, role: "user", content: userContent, created_at: new Date().toISOString() });

    const tempAssistantId = Date.now() + 1;
    addMessage({ id: tempAssistantId, session_id: currentSessionId, role: "assistant", content: "", created_at: new Date().toISOString() });

    setIsStreaming(true);

    let kbParam = "";
    if (selectedKbIds.length > 0) {
      kbParam = `&kb_ids=${selectedKbIds.join(",")}`;
    }

    const url = `${import.meta.env.VITE_API_BASE_URL}/chat/sessions/${currentSessionId}/messages/stream?content=${encodeURIComponent(userContent)}${kbParam}`;

    connect(url, {
      onToken: (token) => {
        appendToLastMessage(token);
      },
      onError: (msg) => {
        message.error(msg);
        setIsStreaming(false);
      },
      onDone: () => {
        setIsStreaming(false);
        getSessions(1, 50).then((res) => setSessions(res.data.data.items));
      },
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ display: "flex", height: "calc(100vh - 112px)", gap: 16 }}>
      {/* 左侧会话列表 */}
      <Card
        style={{ width: 260, flexShrink: 0, overflow: "auto" }}
        styles={{ body: { padding: 12 } }}
      >
        <Button
          type="primary"
          block
          icon={<PlusOutlined />}
          onClick={handleNewSession}
          style={{ marginBottom: 12 }}
        >
          新对话
        </Button>
        <List
          size="small"
          loading={sessionsLoading}
          dataSource={sessions}
          renderItem={(session: ChatSession) => (
            <List.Item
              onClick={() => loadSession(session.id)}
              style={{
                cursor: "pointer",
                padding: "8px 12px",
                borderRadius: 6,
                background: currentSessionId === session.id ? "#e6f4ff" : "transparent",
                marginBottom: 4,
              }}
              actions={[
                <DeleteOutlined
                  key="delete"
                  onClick={(e) => handleDeleteSession(session.id, e)}
                  style={{ color: "#999" }}
                />,
              ]}
            >
              <List.Item.Meta
                title={
                  <Text ellipsis style={{ maxWidth: 160 }}>
                    {session.title}
                  </Text>
                }
                description={
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {session.message_count} 条消息
                  </Text>
                }
              />
            </List.Item>
          )}
          locale={{ emptyText: "暂无会话" }}
        />
      </Card>

      {/* 右侧对话区 */}
      <Card
        style={{ flex: 1, display: "flex", flexDirection: "column" }}
        styles={{ body: { flex: 1, display: "flex", flexDirection: "column", padding: 16 } }}
      >
        {/* 知识库选择 */}
        <div style={{ marginBottom: 12 }}>
          <Space>
            <span style={{ fontSize: 13, color: "#666" }}>知识库：</span>
            <Select
              mode="multiple"
              placeholder="选择知识库（可选）"
              options={kbOptions}
              value={selectedKbIds}
              onChange={setSelectedKbIds}
              style={{ minWidth: 200 }}
              size="small"
              allowClear
            />
          </Space>
        </div>

        {/* 消息列表 */}
        <div
          style={{
            flex: 1,
            overflow: "auto",
            marginBottom: 12,
            padding: "0 4px",
          }}
        >
          {loading ? (
            <div style={{ textAlign: "center", padding: 40 }}>
              <Spin />
            </div>
          ) : messages.length === 0 ? (
            <div style={{ textAlign: "center", padding: 60, color: "#999" }}>
              <Text type="secondary">选择左侧会话或创建新对话开始聊天</Text>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                style={{
                  display: "flex",
                  justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                  marginBottom: 16,
                }}
              >
                <div
                  style={{
                    maxWidth: "70%",
                    padding: "10px 14px",
                    borderRadius: 12,
                    background: msg.role === "user" ? "#1677ff" : "#f0f0f0",
                    color: msg.role === "user" ? "#fff" : "#333",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontSize: 14,
                    lineHeight: 1.6,
                  }}
                >
                  <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>
                    {msg.role === "user" ? "你" : "AI"}
                  </div>
                  {msg.content || (isStreaming ? <Spin size="small" /> : "")}
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区 */}
        <div>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            rows={3}
            disabled={!currentSessionId || isStreaming}
          />
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {currentSessionId ? `会话 #${currentSessionId}` : "请先选择或创建会话"}
            </Text>
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={isStreaming}
              disabled={!currentSessionId || !input.trim()}
            >
              发送
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
