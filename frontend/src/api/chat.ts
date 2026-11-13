// Chat API

import client from "./client";
import type { PaginatedData } from "./knowledgeBase";

export interface ChatSession {
  id: number;
  title: string;
  model_name: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** 引用卡片数据（P2-10）：来自 SSE 的 `event: rag` */
export interface Citation {
  document_id: number;
  document_name: string;
  chunk_index: number;
  similarity: number;
  snippet: string;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  /** 该条回答引用了哪些资料（仅 assistant 且有 RAG 时有值） */
  citations?: Citation[];
}

export interface SessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface ModelOptions {
  models: string[];
  default: string;
  fallbacks: string[];
}

/** 可用模型列表（P2-4）：后端按白名单返回，前端只负责展示 */
export const getModels = () =>
  client.get<{ code: number; data: ModelOptions }>("/chat/models");

export const createSession = (title?: string) =>
  client.post<{ code: number; data: ChatSession }>("/chat/sessions", {
    title: title || "新对话",
  });

export const getSessions = (page = 1, pageSize = 50) =>
  client.get<{ code: number; data: PaginatedData<ChatSession> }>(
    `/chat/sessions?page=${page}&page_size=${pageSize}`
  );

export const getSessionDetail = (id: number) =>
  client.get<{ code: number; data: SessionDetail }>(`/chat/sessions/${id}`);

export const updateSession = (id: number, title: string) =>
  client.put<{ code: number; data: ChatSession }>(`/chat/sessions/${id}`, { title });

export const deleteSession = (id: number) =>
  client.delete<{ code: number }>(`/chat/sessions/${id}`);

export const sendMessage = (
  sessionId: number,
  content: string,
  knowledgeBaseIds?: number[]
) =>
  client.post<{ code: number; data: ChatMessage }>(
    `/chat/sessions/${sessionId}/messages`,
    { content, knowledge_base_ids: knowledgeBaseIds }
  );
