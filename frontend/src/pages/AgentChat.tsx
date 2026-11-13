// Agent 对话页面 — 工具调用可视化 + SSE 流式

import { useState, useRef, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Input, Button, Card, Select, Space, Typography, message, Spin, Tag, Collapse,
} from "antd";
import {
  SendOutlined, RobotOutlined, GlobalOutlined, CalculatorOutlined, StopOutlined,
  BookOutlined, LoadingOutlined,
} from "@ant-design/icons";
import { getKnowledgeBases } from "../api/knowledgeBase";
import { useSSE } from "../hooks/useSSE";
import { API_BASE } from "../api/client";
import MarkdownMessage from "../components/MarkdownMessage";
import { getAgentTools } from "../api/agent";
import type { AgentTool } from "../api/agent";
import { getSessionDetail } from "../api/chat";

const { TextArea } = Input;
const { Text } = Typography;
const { Panel } = Collapse;

interface ToolCallItem {
  name: string;
  arguments: string;
  result?: string;
  status: "running" | "done" | "error";
}

interface MessageItem {
  id: number;
  role: "user" | "assistant" | "tool_call";
  content: string;
  toolCalls?: ToolCallItem[];
}

const toolIcons: Record<string, React.ReactNode> = {
  web_search: <GlobalOutlined />,
  calculator: <CalculatorOutlined />,
  knowledge_retrieval: <BookOutlined />,
};

const toolNames: Record<string, string> = {
  web_search: "联网搜索",
  calculator: "计算器",
  knowledge_retrieval: "知识库检索",
};

export default function AgentChat() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [kbOptions, setKbOptions] = useState<{ label: string; value: number }[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([]);
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [currentToolCalls, setCurrentToolCalls] = useState<ToolCallItem[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { connect, stop } = useSSE();
  const msgIdRef = useRef(0);

  const [searchParams] = useSearchParams();
  const [sessionId, setSessionId] = useState<number | null>(null);
  // 用 ref 保存"最新值"：onDone 是连接建立那一刻形成的闭包，读不到之后的 state 更新。
  // 这正是 P0-5「流式结束后答案变空」的根因。
  const streamContentRef = useRef("");
  const toolCallsRef = useRef<ToolCallItem[]>([]);

  useEffect(() => {
    const init = async () => {
      try {
        const [kbRes, toolRes] = await Promise.all([
          getKnowledgeBases(1, 50),
          getAgentTools(true),
        ]);
        setKbOptions(
          kbRes.data.data.items.map((kb: any) => ({ label: kb.name, value: kb.id }))
        );
        setTools(toolRes.data.data);
      } catch {
        // ignore
      }
    };
    init();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamContent, currentToolCalls]);

  // 从 URL 的 session_id 恢复历史（刷新页面后对话仍然在，而不是白屏）
  useEffect(() => {
    const sid = searchParams.get("session_id");
    if (!sid) return;

    const loadHistory = async () => {
      try {
        const res = await getSessionDetail(Number(sid));
        const detail = res.data.data;
        setSessionId(detail.id);
        setMessages(
          detail.messages.map((m) => ({
            id: ++msgIdRef.current,
            role: m.role,
            content: m.content,
          }))
        );
      } catch {
        message.error("加载历史对话失败");
      }
    };
    loadHistory();
  }, [searchParams]);

  const nextId = () => ++msgIdRef.current;

  const getToolIcon = (name: string) => toolIcons[name] || <RobotOutlined />;
  const getToolName = (name: string) => toolNames[name] || name;

  const handleSend = () => {
    if (!input.trim() || isStreaming) return;

    const userContent = input.trim();
    setInput("");

    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: userContent },
    ]);

    setIsStreaming(true);
    setStreamContent("");
    setCurrentToolCalls([]);
    streamContentRef.current = "";
    toolCallsRef.current = [];

    // 消息内容与 session_id 都走 POST body（P1-12）
    const url = `${API_BASE}/agent/chat/stream`;

    connect(
      url,
      {
        onSession: (data) => {
          // 后端首次会新建会话并回传 id，记住它，后续追问才在同一个会话里
          if (data?.session_id) setSessionId(data.session_id);
        },
        onToolCall: (data) => {
          toolCallsRef.current = [
            ...toolCallsRef.current,
            { name: data.name, arguments: data.arguments, status: "running" },
          ];
          setCurrentToolCalls(toolCallsRef.current);
        },
        onToolResult: (data) => {
          toolCallsRef.current = toolCallsRef.current.map((tc) =>
            tc.name === data.name
              ? { ...tc, result: data.result, status: "done" as const }
              : tc
          );
          setCurrentToolCalls(toolCallsRef.current);
        },
        onToken: (token) => {
          streamContentRef.current += token;
          setStreamContent(streamContentRef.current);
        },
        onDone: () => {
          // 从 ref 读最新值：闭包里的 streamContent / currentToolCalls 是连接建立那一刻的旧值
          const finalContent = streamContentRef.current;
          const finalToolCalls = toolCallsRef.current;
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "assistant",
              content: finalContent,
              toolCalls: finalToolCalls.length > 0 ? [...finalToolCalls] : undefined,
            },
          ]);
          setIsStreaming(false);
          setStreamContent("");
          setCurrentToolCalls([]);
          streamContentRef.current = "";
          toolCallsRef.current = [];
        },
        onError: (msg) => {
          message.error(msg);
          // 已经收到的部分回答不要丢：追加一条带中断说明的消息
          const partial = streamContentRef.current;
          if (partial) {
            setMessages((prev) => [
              ...prev,
              {
                id: nextId(),
                role: "assistant",
                content: `${partial}\n\n（生成中断：${msg}）`,
              },
            ]);
          }
          setIsStreaming(false);
          setStreamContent("");
          setCurrentToolCalls([]);
          streamContentRef.current = "";
          toolCallsRef.current = [];
        },
      },
      {
        // 消息内容与 session_id 都走 body
        method: "POST",
        body: {
          content: userContent,
          session_id: sessionId,
          knowledge_base_ids: selectedKbIds,
        },
      }
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ display: "flex", height: "calc(100vh - 112px)", gap: 16 }}>
      {/* 左侧工具信息 */}
      <Card
        title="可用工具"
        style={{ width: 240, flexShrink: 0, overflow: "auto" }}
        styles={{ body: { padding: 12 } }}
      >
        {tools.map((tool) => (
          <div
            key={tool.id}
            style={{
              padding: "8px 12px",
              marginBottom: 8,
              borderRadius: 6,
              background: "#f5f5f5",
            }}
          >
            <Space>
              {getToolIcon(tool.name)}
              <Text strong>{tool.display_name}</Text>
            </Space>
            <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
              {tool.description}
            </div>
          </div>
        ))}
        <div style={{ marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Agent 会自动判断是否需要调用工具
          </Text>
        </div>
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
        <div style={{ flex: 1, overflow: "auto", marginBottom: 12 }}>
          {messages.length === 0 && !isStreaming ? (
            <div style={{ textAlign: "center", padding: 60, color: "#999" }}>
              <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
              <br />
              <Text type="secondary">
                Agent 可以调用工具来回答你的问题
                <br />
                试试：搜索今日新闻、计算 1024*768、查知识库中的资料
              </Text>
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} style={{ marginBottom: 16 }}>
                {msg.role === "user" ? (
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <div
                      style={{
                        maxWidth: "70%",
                        padding: "10px 14px",
                        borderRadius: 12,
                        background: "#1677ff",
                        color: "#fff",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        fontSize: 14,
                        lineHeight: 1.6,
                      }}
                    >
                      <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>你</div>
                      {msg.content}
                    </div>
                  </div>
                ) : (
                  <div style={{ display: "flex", justifyContent: "flex-start" }}>
                    <div style={{ maxWidth: "80%" }}>
                      {msg.toolCalls && msg.toolCalls.length > 0 && (
                        <div style={{ marginBottom: 8 }}>
                          <Collapse ghost size="small">
                            <Panel
                              header={
                                <Space>
                                  <RobotOutlined />
                                  <Text style={{ fontSize: 13 }}>
                                    调用了 {msg.toolCalls.length} 个工具
                                  </Text>
                                </Space>
                              }
                              key="tools"
                            >
                              {msg.toolCalls.map((tc, idx) => (
                                <div
                                  key={idx}
                                  style={{
                                    padding: "6px 10px",
                                    marginBottom: 4,
                                    background: "#f6ffed",
                                    borderRadius: 6,
                                    fontSize: 13,
                                  }}
                                >
                                  <Space>
                                    {getToolIcon(tc.name)}
                                    <Text strong>{getToolName(tc.name)}</Text>
                                    <Tag color="green">完成</Tag>
                                  </Space>
                                  {tc.result && (
                                    <div
                                      style={{
                                        marginTop: 4,
                                        padding: 8,
                                        background: "#fff",
                                        borderRadius: 4,
                                        fontSize: 12,
                                        color: "#666",
                                        maxHeight: 100,
                                        overflow: "auto",
                                      }}
                                    >
                                      {tc.result.length > 200 ? tc.result.slice(0, 200) + "..." : tc.result}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </Panel>
                          </Collapse>
                        </div>
                      )}
                      <div
                        style={{
                          padding: "10px 14px",
                          borderRadius: 12,
                          background: "#f0f0f0",
                          color: "#333",
                          wordBreak: "break-word",
                          fontSize: 14,
                          lineHeight: 1.6,
                        }}
                      >
                        <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>AI</div>
                        <MarkdownMessage content={msg.content} />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))
          )}

          {/* 正在执行中的工具调用 */}
          {isStreaming && currentToolCalls.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <Collapse ghost size="small" defaultActiveKey={["tools"]}>
                <Panel
                  header={
                    <Space>
                      <LoadingOutlined />
                      <Text style={{ fontSize: 13 }}>正在调用工具...</Text>
                    </Space>
                  }
                  key="tools"
                >
                  {currentToolCalls.map((tc, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "6px 10px",
                        marginBottom: 4,
                        background: tc.status === "done" ? "#f6ffed" : "#fff7e6",
                        borderRadius: 6,
                        fontSize: 13,
                      }}
                    >
                      <Space>
                        {getToolIcon(tc.name)}
                        <Text strong>{getToolName(tc.name)}</Text>
                        <Tag color={tc.status === "done" ? "green" : "processing"}>
                          {tc.status === "running" ? "执行中..." : "完成"}
                        </Tag>
                      </Space>
                    </div>
                  ))}
                </Panel>
              </Collapse>
            </div>
          )}

          {/* 流式输出中的内容 */}
          {isStreaming && streamContent && (
            <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
              <div
                style={{
                  maxWidth: "80%",
                  padding: "10px 14px",
                  borderRadius: 12,
                  background: "#f0f0f0",
                  color: "#333",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: 14,
                  lineHeight: 1.6,
                }}
              >
                <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>AI</div>
                <MarkdownMessage content={streamContent} />
                <Spin size="small" style={{ marginLeft: 4 }} />
              </div>
            </div>
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
            disabled={isStreaming}
          />
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
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
                disabled={!input.trim()}
              >
                发送
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
