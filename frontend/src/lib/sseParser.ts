// SSE 帧解析（P2-11）——纯函数，不碰 DOM、不碰网络，可以单测
//
// 规范要点（以前实现漏掉的）：
//   1. 帧以**空行**分隔，不是以 `\n` 分隔 —— 一帧里可以有多行
//   2. 一帧允许多个 `data:` 行，客户端要用 `\n` 拼接
//   3. `event:` 指定事件名，缺省是 "message"
//   4. `:` 开头是注释（心跳），必须忽略
//   5. 行尾可能是 \n 或 \r\n
//   6. 一个网络分片里可能有半帧、也可能有多帧

export interface SSEFrame {
  event: string;
  data: string;
  id?: string;
}

export interface SSEParser {
  /** 喂一段网络分片，返回这段里能切出的完整帧 */
  push(chunk: string): SSEFrame[];
  /** 流结束时调用：把残留的最后一帧（没有以空行结尾的）也吐出来 */
  flush(): SSEFrame[];
}

/** 判定"这一行是不是字段行"，用于区分"半帧"和"真空行" */
function splitFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = [];
  let cursor = 0;

  while (true) {
    const lf = buffer.indexOf("\n\n", cursor);
    const crlf = buffer.indexOf("\r\n\r\n", cursor);
    // 找最早出现的那个分隔符
    let index = -1;
    let length = 0;
    if (lf === -1 && crlf === -1) break;
    if (crlf !== -1 && (lf === -1 || crlf < lf)) {
      index = crlf;
      length = 4;
    } else {
      index = lf;
      length = 2;
    }
    frames.push(buffer.slice(cursor, index));
    cursor = index + length;
  }

  return { frames, rest: buffer.slice(cursor) };
}

function parseFrame(raw: string): SSEFrame | null {
  const lines = raw.split(/\r?\n/);
  const dataLines: string[] = [];
  let event = "";
  let id: string | undefined;

  for (const line of lines) {
    if (!line || line.startsWith(":")) continue; // 空行 / 注释（心跳）
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1); // 规范：吃掉一个前导空格

    switch (field) {
      case "event":
        event = value;
        break;
      case "data":
        dataLines.push(value);
        break;
      case "id":
        id = value;
        break;
      case "retry":
        break; // 重连间隔：本项目的重连由 hook 控制，这里忽略
      default:
        break; // 未知字段按规范忽略
    }
  }

  if (dataLines.length === 0) return null; // 没有 data 的帧不产生事件
  return { event: event || "message", data: dataLines.join("\n"), id };
}

export function createSSEParser(): SSEParser {
  let buffer = "";

  return {
    push(chunk: string): SSEFrame[] {
      buffer += chunk;
      const { frames, rest } = splitFrames(buffer);
      buffer = rest;
      const events: SSEFrame[] = [];
      for (const frame of frames) {
        const parsed = parseFrame(frame);
        if (parsed) events.push(parsed);
      }
      return events;
    },

    flush(): SSEFrame[] {
      const rest = buffer;
      buffer = "";
      if (!rest.trim()) return [];
      const parsed = parseFrame(rest);
      return parsed ? [parsed] : [];
    },
  };
}

/** 尝试把 data 解析成 JSON；失败时返回原始字符串（后端偶尔会发明文） */
export function parseSSEData(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
}
