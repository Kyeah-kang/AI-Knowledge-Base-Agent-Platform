// SSE 流式读取 Hook —— 薄封装（P2-11）
//
// 真正的解析与断流/重试逻辑在 `lib/sseParser.ts` 与 `lib/sseClient.ts`（已单测）。
// 这里只做三件事：拿 token、把帧翻译成业务回调、把最终结果翻译成 onDone/onError/onAborted。

import { useCallback, useRef } from "react";
import { parseSSEData } from "../lib/sseParser";
import { streamSSE } from "../lib/sseClient";

export type SSEOptions = {
  /** 默认 POST：消息内容走 body，不再放进 URL（P1-12） */
  method?: "GET" | "POST";
  /** POST 时的 JSON 请求体 */
  body?: unknown;
  /** 网络失败且尚未输出任何 token 时的重试次数（默认 1） */
  retries?: number;
};

type SSEEventHandler = {
  onToken?: (token: string) => void;
  onToolCall?: (data: any) => void;
  onToolResult?: (data: any) => void;
  onRag?: (data: any) => void;
  onSession?: (data: any) => void;
  onError?: (msg: string) => void;
  onDone?: (data: any) => void;
  /** 用户主动停止（与 onError 区分：停止不算失败） */
  onAborted?: () => void;
};

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(
    async (url: string, handlers: SSEEventHandler, options: SSEOptions = {}) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const accessToken = localStorage.getItem("access_token");
      let donePayload: any = null;
      let doneSeen = false;

      const outcome = await streamSSE({
        url,
        method: options.method ?? "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
        body: options.body,
        retries: options.retries,
        signal: controller.signal,
        onFrame: (frame) => {
          const payload = parseSSEData(frame.data) as Record<string, any>;

          switch (frame.event) {
            case "token":
              handlers.onToken?.(payload?.token ?? "");
              break;
            case "tool_call":
              handlers.onToolCall?.(payload);
              break;
            case "tool_result":
              handlers.onToolResult?.(payload);
              break;
            case "rag":
              handlers.onRag?.(payload);
              break;
            case "session":
              handlers.onSession?.(payload);
              break;
            case "error":
              handlers.onError?.(payload?.message ?? String(frame.data));
              break;
            case "done":
              doneSeen = true;
              donePayload = payload;
              break;
            default:
              // 普通聊天用"无事件名 + {token, done}"的格式
              if (payload?.token !== undefined) {
                handlers.onToken?.(payload.token);
              }
              if (payload?.done === true) {
                doneSeen = true;
                donePayload = payload;
              }
              break;
          }
        },
      });

      if (outcome.status === "aborted") {
        handlers.onAborted?.();
        return outcome;
      }
      if (outcome.status === "done") {
        handlers.onDone?.(donePayload);
        return outcome;
      }
      if (outcome.status === "error" || outcome.status === "http_error") {
        // 服务端已经发过 event: error 时错误提示已经给过了，这里避免重复弹
        if (!doneSeen) handlers.onError?.(outcome.message ?? "请求失败");
      }
      return outcome;
    },
    []
  );

  /** 用户点"停止生成" */
  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  /** 兼容旧调用名 */
  const disconnect = stop;

  return { connect, stop, disconnect };
}
