// SSE 流式读取 Hook — 用于智能对话和 Agent 对话

import { useCallback, useRef } from "react";

type SSEEventHandler = {
  onToken?: (token: string) => void;
  onToolCall?: (data: any) => void;
  onToolResult?: (data: any) => void;
  onRag?: (data: any) => void;
  onSession?: (data: any) => void;
  onError?: (msg: string) => void;
  onDone?: (data: any) => void;
};

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(
    async (url: string, handlers: SSEEventHandler) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const token = localStorage.getItem("access_token");
      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok) {
          handlers.onError?.(`HTTP ${response.status}`);
          return;
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          let currentEvent = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);
                switch (currentEvent) {
                  case "token":
                    handlers.onToken?.(data.token);
                    break;
                  case "tool_call":
                    handlers.onToolCall?.(data);
                    break;
                  case "tool_result":
                    handlers.onToolResult?.(data);
                    break;
                  case "rag":
                    handlers.onRag?.(data);
                    break;
                  case "session":
                    handlers.onSession?.(data);
                    break;
                  case "error":
                    handlers.onError?.(data.message || data);
                    break;
                  case "done":
                    handlers.onDone?.(data);
                    break;
                  default:
                    // 普通 SSE（兼容 chat 的简单格式）
                    if (data.token !== undefined) {
                      handlers.onToken?.(data.token);
                    }
                    break;
                }
              } catch {
                // 非 JSON 数据
              }
              currentEvent = "";
            } else if (line.startsWith(":") || line.trim() === "") {
              // 注释行或空行，忽略
            }
          }
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          handlers.onError?.(err.message);
        }
      }
    },
    []
  );

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { connect, disconnect };
}
