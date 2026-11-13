// 智能对话页面 — SSE 流式输出 + 知识库选择

import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Input, Button, Card, List, Select, Space, Typography, message, Spin, Tooltip,
} from "antd";
import {
  SendOutlined, PlusOutlined, DeleteOutlined, StopOutlined, ReloadOutlined,
} from "@ant-design/icons";
import MarkdownMessage from "../components/MarkdownMessage";
import CitationList from "../components/CitationList";
import type { Citation } from "../api/chat";
import {
  getSessions, createSession, getSessionDetail, deleteSession, getModels,
} from "../api/chat";
import { getKnowledgeBases } from "../api/knowledgeBase";
import { API_BASE } from "../api/client";
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
    setIsStreaming, appendToLastMessage, patchLastMessage, removeLastMessage, reset,
  } = useChatStore();

  const [input, setInput] = useState("");
  const [kbOptions, setKbOptions] = useState<{ label: string; value: number }[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  // P2-4：模型选择（不选就用后端默认；选项来自 /chat/models 白名单）
  const [models, setModels] = useState<string[]>([]);
  const [modelName, setModelName] = useState<string | undefined>(undefined);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { connect, stop } = useSSE();
  // 本轮 RAG 引用：放 ref 里，因为 onDone 是连接建立那一刻的闭包（读 state 会拿到旧值）
  const citationsRef = useRef<Citation[]>([]);
  // 上一轮发的内容，用于"重试"
  const lastSentRef = useRef<{ content: string; kbIds: number[] } | null>(null);

  // 加载会话列表 + 知识库列表
  useEffect(() => {
    const init = async () => {
      setSessionsLoading(true);
      try {
        const [sessionRes, kbRes, modelRes] = await Promise.all([
          getSessions(1, 50),
          getKnowledgeBases(1, 50),
          getModels(),
        ]);
        setSessions(sessionRes.data.data.items);
        setModels(modelRes.data.data.models);
        setModelName(modelRes.data.data.default);
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

  /** 真正发送一轮（重试也走这里） */
  const sendMessage = (userContent: string, kbIds: number[]) => {
    if (!currentSessionId) return;

    lastSentRef.current = { content: userContent, kbIds };
    citationsRef.current = [];

    addMessage({ id: Date.now(), session_id: currentSessionId, role: "user", content: userContent, created_at: new Date().toISOString() });
    addMessage({ id: Date.now() + 1, session_id: currentSessionId, role: "assistant", content: "", created_at: new Date().toISOString() });

    setIsStreaming(true);

    // 消息内容走 POST body，不再拼进 URL（P1-12：避免进入访问日志/浏览器历史）
    const url = `${API_BASE}/chat/sessions/${currentSessionId}/messages/stream`;

    connect(
      url,
      {
        onToken: (token) => {
          appendToLastMessage(token);
        },
        onRag: (data) => {
          citationsRef.current = data?.citations ?? [];
        },
        onError: (msg) => {
          // 错误不能只弹个 toast 就消失：写进当前气泡，用户回头还能看到"这轮失败了"
          appendToLastMessage(`\n\n（回答失败：${msg}）`);
          message.error(msg);
          setIsStreaming(false);
        },
        onAborted: () => {
          // 用户主动停止：保留已收到的内容，明确标注，不当成失败
          appendToLastMessage("\n\n（已停止生成）");
          setIsStreaming(false);
        },
        onDone: () => {
          // 把本轮引用挂到最后一条回答上，渲染成引用卡片
          if (citationsRef.current.length > 0) {
            patchLastMessage({ citations: [...citationsRef.current] });
          }
          setIsStreaming(false);
          getSessions(1, 50).then((res) => setSessions(res.data.data.items));
        },
      },
      {
        // 消息内容走 body，不放进 URL
        method: "POST",
        body: {
          content: userContent,
          knowledge_base_ids: kbIds,
          // P2-4：这一轮用哪个模型（后端会按白名单校验）
          model_name: modelName,
        },
      }
    );
  };

  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    if (!currentSessionId) {
      message.warning("请先选择或创建一个会话");
      return;
    }
    const userContent = input.trim();
    setInput("");
    sendMessage(userContent, selectedKbIds);
  };

  /** 重试上一轮：先去掉失败/停止的那条回答，再原样重发 */
  const handleRetry = () => {
    const last = lastSentRef.current;
    if (!last || isStreaming) return;
    removeLastMessage(); // 失败的回答
    removeLastMessage(); // 对应的提问（sendMessage 会重新加回来）
    sendMessage(last.content, last.kbIds);
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
                    maxWidth: msg.role === "user" ? "70%" : "80%",
                    padding: "10px 14px",
                    borderRadius: 12,
                    background: msg.role === "user" ? "#1677ff" : "#f0f0f0",
                    color: msg.role === "user" ? "#fff" : "#333",
                    whiteSpace: msg.role === "user" ? "pre-wrap" : "normal",
                    wordBreak: "break-word",
                    fontSize: 14,
                    lineHeight: 1.6,
                  }}
                >
                  <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>
                    {msg.role === "user" ? "你" : "AI"}
                  </div>
                  {msg.role === "user" ? (
                    msg.content
                  ) : msg.content ? (
                    // P2-10：回答按 Markdown 渲染（列表/表格/代码块）
                    <MarkdownMessage content={msg.content} />
                  ) : isStreaming ? (
                    <Spin size="small" />
                  ) : null}
                  {/* P2-10：引用卡片（来自 SSE 的 event: rag） */}
                  {msg.role === "assistant" && (
                    <CitationList citations={msg.citations ?? []} />
                  )}
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区 */}
        <div>
          <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              模型
            </Text>
            <Select
              size="small"
              style={{ width: 220 }}
              value={modelName}
              onChange={setModelName}
              options={models.map((m) => ({ label: m, value: m }))}
              placeholder="默认模型"
              disabled={isStreaming}
            />
          </div>
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
            <Space>
              {lastSentRef.current && !isStreaming && (
                <Tooltip title="重新发送上一轮问题">
                  <Button icon={<ReloadOutlined />} onClick={handleRetry}>
                    重试
                  </Button>
                </Tooltip>
              )}
              {isStreaming ? (
                // P2-10：生成中可停止，已收到的内容会保留
                <Button danger icon={<StopOutlined />} onClick={stop}>
                  停止生成
                </Button>
              ) : (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  onClick={handleSend}
                  disabled={!currentSessionId || !input.trim()}
                >
                  发送
                </Button>
              )}
            </Space>
          </div>
        </div>
      </Card>
    </div>
  );
}
