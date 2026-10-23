// Agent 对话页面 — 工具调用可视化 + SSE 流式

import { useState, useRef, useEffect } from "react";
import {
  Input, Button, Card, Select, Space, Typography, message, Spin, Tag, Collapse,
} from "antd";
import {
  SendOutlined, RobotOutlined, GlobalOutlined, CalculatorOutlined,
  BookOutlined, LoadingOutlined,
} from "@ant-design/icons";
import { getKnowledgeBases } from "../api/knowledgeBase";
import { useSSE } from "../hooks/useSSE";
import { getAgentTools } from "../api/agent";
import type { AgentTool } from "../api/agent";

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
  const { connect } = useSSE();
  const msgIdRef = useRef(0);

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

    let kbParam = "";
    if (selectedKbIds.length > 0) {
      kbParam = `&kb_ids=${selectedKbIds.join(",")}`;
    }

    const url = `${import.meta.env.VITE_API_BASE_URL}/agent/chat/stream?content=${encodeURIComponent(userContent)}${kbParam}`;

    connect(url, {
      onToolCall: (data) => {
        setCurrentToolCalls((prev) => [
          ...prev,
          { name: data.name, arguments: data.arguments, status: "running" },
        ]);
      },
      onToolResult: (data) => {
        setCurrentToolCalls((prev) =>
          prev.map((tc) =>
            tc.name === data.name
              ? { ...tc, result: data.result, status: "done" }
              : tc
          )
        );
      },
      onToken: (token) => {
        setStreamContent((prev) => prev + token);
      },
      onDone: () => {
        setIsStreaming(false);
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            content: streamContent,
            toolCalls: currentToolCalls.length > 0 ? [...currentToolCalls] : undefined,
          },
        ]);
        setStreamContent("");
        setCurrentToolCalls([]);
      },
      onError: (msg) => {
        message.error(msg);
        setIsStreaming(false);
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
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          fontSize: 14,
                          lineHeight: 1.6,
                        }}
                      >
                        <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>AI</div>
                        {msg.content}
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
                {streamContent}
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
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={isStreaming}
              disabled={!input.trim()}
            >
              发送
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
