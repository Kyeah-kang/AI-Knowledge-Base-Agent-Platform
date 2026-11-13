// SSE 流消费的单测（P2-11）
//
// 重点验证"断线"的三种表现：
//   - 没收到 done 就断了 → 报"连接中断"
//   - 断之前还没吐 token → 自动重试一次
//   - 断之前已经吐过 token → 不重试（否则重复内容）

import { describe, expect, it, vi } from "vitest";
import { streamSSE } from "./sseClient";
import type { SSEFrame } from "./sseParser";

function responseFromChunks(chunks: string[], ok = true) {
  let index = 0;
  return {
    ok,
    status: ok ? 200 : 500,
    body: {
      getReader: () => ({
        read: async () => {
          if (index >= chunks.length) return { done: true, value: undefined };
          const value = new TextEncoder().encode(chunks[index++]);
          return { done: false, value };
        },
      }),
    },
  } as unknown as Response;
}

const noSleep = async () => undefined;

describe("streamSSE", () => {
  it("正常流：收到 done 即结束", async () => {
    const frames: SSEFrame[] = [];
    const outcome = await streamSSE({
      url: "/x",
      fetchImpl: async () =>
        responseFromChunks([
          'data: {"token":"你"}\n\n',
          'data: {"token":"好"}\n\n',
          'data: {"token":"","done":true}\n\n',
        ]),
      onFrame: (frame) => frames.push(frame),
      sleepImpl: noSleep,
    });

    expect(outcome.status).toBe("done");
    expect(frames).toHaveLength(3);
  });

  it("没收到 done 就断流 → 报连接中断", async () => {
    const outcome = await streamSSE({
      url: "/x",
      fetchImpl: async () => responseFromChunks(['data: {"token":"半句"}\n\n']),
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(outcome.status).toBe("error");
    expect(outcome.message).toContain("连接中断");
  });

  it("断流且尚未吐 token → 自动重试一次后成功", async () => {
    let calls = 0;
    const outcome = await streamSSE({
      url: "/x",
      retries: 1,
      fetchImpl: async () => {
        calls += 1;
        if (calls === 1) return responseFromChunks([]); // 第一次直接断，没有 token
        return responseFromChunks(['event: done\ndata: {"ok":true}\n\n']);
      },
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(calls).toBe(2);
    expect(outcome.status).toBe("done");
    expect(outcome.attempts).toBe(2);
  });

  it("已经吐过 token 后断流 → 不重试（避免重复内容）", async () => {
    let calls = 0;
    const outcome = await streamSSE({
      url: "/x",
      retries: 3,
      fetchImpl: async () => {
        calls += 1;
        return responseFromChunks(['data: {"token":"已输出"}\n\n']);
      },
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(calls).toBe(1);
    expect(outcome.status).toBe("error");
  });

  it("HTTP 非 2xx → 直接报错，不重试", async () => {
    let calls = 0;
    const outcome = await streamSSE({
      url: "/x",
      fetchImpl: async () => {
        calls += 1;
        return responseFromChunks([], false);
      },
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(calls).toBe(1);
    expect(outcome.status).toBe("http_error");
    expect(outcome.message).toBe("HTTP 500");
  });

  it("服务端 event: error → 状态 error 且带消息", async () => {
    const outcome = await streamSSE({
      url: "/x",
      fetchImpl: async () =>
        responseFromChunks([
          'event: error\ndata: {"message":"向量库未连接","code":503}\n\n',
          "event: done\ndata: {}\n\n",
        ]),
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(outcome.status).toBe("error");
    expect(outcome.message).toBe("向量库未连接");
  });

  it("用户主动停止 → aborted（不当成错误）", async () => {
    const controller = new AbortController();
    controller.abort();

    const outcome = await streamSSE({
      url: "/x",
      signal: controller.signal,
      fetchImpl: async () => {
        throw Object.assign(new Error("aborted"), { name: "AbortError" });
      },
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(outcome.status).toBe("aborted");
  });

  it("网络异常且未吐 token → 重试后仍失败则 error", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("network down");
    });
    const outcome = await streamSSE({
      url: "/x",
      retries: 1,
      fetchImpl,
      onFrame: () => undefined,
      sleepImpl: noSleep,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(outcome.status).toBe("error");
    expect(outcome.message).toContain("network down");
  });
});
