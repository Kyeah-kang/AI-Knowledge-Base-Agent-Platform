// SSE 流消费（P2-11）—— 与 React 无关，纯 async 函数，可单测
//
// 负责三件旧实现没做的事：
//   1. 流结束但既没 done 也没 error → 判定为"连接中断"（以前安静地当成功）
//   2. 网络失败且**尚未输出任何 token** → 自动重试（已经吐过就不能重试，
//      否则用户会看到重复片段）
//   3. 区分"用户主动停止"和"出错"（停止不该弹错误提示）

import { createSSEParser, parseSSEData, type SSEFrame } from "./sseParser";

export type StreamOutcomeStatus = "done" | "error" | "aborted" | "http_error";

export interface StreamOutcome {
  status: StreamOutcomeStatus;
  message?: string;
  attempts: number;
}

export interface StreamParams {
  url: string;
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  body?: unknown;
  /** 尚未输出 token 时的最大重试次数（默认 1） */
  retries?: number;
  signal?: AbortSignal;
  onFrame: (frame: SSEFrame) => void;
  /** 仅测试注入；默认用全局 fetch / 真实等待 */
  fetchImpl?: typeof fetch;
  sleepImpl?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** 这一帧是否算"已经给用户看到内容了"（决定还能不能重试） */
export function frameHasToken(frame: SSEFrame): boolean {
  if (frame.event === "token") return true;
  const data = parseSSEData(frame.data) as Record<string, unknown> | string;
  if (typeof data !== "object" || data === null) return false;
  return typeof (data as Record<string, unknown>).token === "string";
}

function frameIsDone(frame: SSEFrame): boolean {
  if (frame.event === "done") return true;
  const data = parseSSEData(frame.data);
  return typeof data === "object" && data !== null && (data as any).done === true;
}

function frameIsError(frame: SSEFrame): boolean {
  if (frame.event === "error") return true;
  const data = parseSSEData(frame.data);
  return typeof data === "object" && data !== null && Boolean((data as any).error);
}

export async function streamSSE(params: StreamParams): Promise<StreamOutcome> {
  const fetchImpl = params.fetchImpl ?? globalThis.fetch;
  const sleep = params.sleepImpl ?? defaultSleep;
  const method = params.method ?? "POST";
  const maxRetries = params.retries ?? 1;
  const headers = { ...(params.headers ?? {}) };
  if (method === "POST") headers["Content-Type"] = "application/json";

  let attempt = 0;

  while (true) {
    attempt += 1;
    const parser = createSSEParser();
    let sawDone = false;
    let sawError = false;
    let sawToken = false;
    let errorMessage: string | undefined;

    const handle = (frame: SSEFrame) => {
      if (frameHasToken(frame)) sawToken = true;
      if (frameIsDone(frame)) sawDone = true;
      if (frameIsError(frame)) {
        sawError = true;
        const data = parseSSEData(frame.data) as any;
        errorMessage = data?.message ?? data?.error ?? "服务端返回错误";
      }
      params.onFrame(frame);
    };

    try {
      const response = await fetchImpl(params.url, {
        method,
        headers,
        body: method === "POST" ? JSON.stringify(params.body ?? {}) : undefined,
        signal: params.signal,
      });

      if (!response.ok) {
        return { status: "http_error", message: `HTTP ${response.status}`, attempts: attempt };
      }
      if (!response.body) {
        return { status: "error", message: "响应没有数据流", attempts: attempt };
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
          handle(frame);
        }
      }
      for (const frame of parser.flush()) handle(frame);

      if (params.signal?.aborted) {
        return { status: "aborted", attempts: attempt };
      }
      if (sawError) {
        return { status: "error", message: errorMessage, attempts: attempt };
      }
      if (!sawDone) {
        // 连接被端掉，但既没 done 也没 error
        if (attempt <= maxRetries && !sawToken) {
          await sleep(300);
          continue;
        }
        return {
          status: "error",
          message: "连接中断：没有收到结束信号",
          attempts: attempt,
        };
      }
      return { status: "done", attempts: attempt };
    } catch (err: any) {
      if (err?.name === "AbortError" || params.signal?.aborted) {
        return { status: "aborted", attempts: attempt };
      }
      if (attempt <= maxRetries && !sawToken) {
        await sleep(300);
        continue;
      }
      return {
        status: "error",
        message: err?.message ?? String(err),
        attempts: attempt,
      };
    }
  }
}
