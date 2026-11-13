// SSE 解析器单测（P2-11）
//
// 这些用例锁的都是"以前会解析错"的场景：
//   多行 data、一帧跨多个网络分片、\r\n、注释心跳、没有 data 的帧、
//   以及"流断了但没收到 done"这种必须报错的场景（由 hook 层负责，见下）

import { describe, expect, it } from "vitest";
import { createSSEParser, parseSSEData } from "./sseParser";

const feed = (chunks: string[]) => {
  const parser = createSSEParser();
  const frames = chunks.flatMap((chunk) => parser.push(chunk));
  return [...frames, ...parser.flush()];
};

describe("createSSEParser", () => {
  it("解析单帧 event + data", () => {
    const frames = feed(["event: token\ndata: {\"token\":\"你\"}\n\n"]);

    expect(frames).toHaveLength(1);
    expect(frames[0].event).toBe("token");
    expect(parseSSEData(frames[0].data)).toEqual({ token: "你" });
  });

  it("没有 event 字段时默认是 message", () => {
    const frames = feed(['data: {"token":"hi","done":false}\n\n']);

    expect(frames[0].event).toBe("message");
  });

  it("多行 data 用 \\n 拼接（以前只取第一行）", () => {
    const frames = feed(["data: 第一行\ndata: 第二行\n\n"]);

    expect(frames[0].data).toBe("第一行\n第二行");
  });

  it("一帧被拆到多个网络分片里也能拼回来", () => {
    const parser = createSSEParser();
    const first = parser.push("event: tok");
    const second = parser.push("en\ndata: {\"token\":\"拆");
    const third = parser.push("开\"}\n\n");

    expect([...first, ...second]).toHaveLength(0);
    expect(third).toHaveLength(1);
    expect(third[0].event).toBe("token");
    expect(parseSSEData(third[0].data)).toEqual({ token: "拆开" });
  });

  it("一个分片里有多帧时全部吐出", () => {
    const frames = feed([
      'data: {"token":"a"}\n\ndata: {"token":"b"}\n\ndata: {"token":"c"}\n\n',
    ]);

    expect(frames.map((f) => parseSSEData(f.data))).toEqual([
      { token: "a" },
      { token: "b" },
      { token: "c" },
    ]);
  });

  it("支持 \\r\\n 换行", () => {
    const frames = feed(['event: done\r\ndata: {"done":true}\r\n\r\n']);

    expect(frames).toHaveLength(1);
    expect(frames[0].event).toBe("done");
    expect(parseSSEData(frames[0].data)).toEqual({ done: true });
  });

  it("忽略注释心跳（: 开头）", () => {
    const frames = feed([": keep-alive\n\ndata: {\"token\":\"x\"}\n\n"]);

    expect(frames).toHaveLength(1);
    expect(parseSSEData(frames[0].data)).toEqual({ token: "x" });
  });

  it("没有 data 的帧不产生事件", () => {
    const frames = feed(["event: ping\n\n", 'data: {"token":"ok"}\n\n']);

    expect(frames).toHaveLength(1);
  });

  it("flush 吐出没有以空行结尾的最后一帧", () => {
    const parser = createSSEParser();
    parser.push('data: {"token":"尾巴"}');

    const rest = parser.flush();

    expect(rest).toHaveLength(1);
    expect(parseSSEData(rest[0].data)).toEqual({ token: "尾巴" });
  });

  it("非法 JSON 时退化成原始字符串而不是抛错", () => {
    const frames = feed(["data: not-json\n\n"]);

    expect(parseSSEData(frames[0].data)).toBe("not-json");
  });

  it("id 字段会被保留（供以后做断点续传）", () => {
    const frames = feed(["id: 42\ndata: {}\n\n"]);

    expect(frames[0].id).toBe("42");
  });
});
