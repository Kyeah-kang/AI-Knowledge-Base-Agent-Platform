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

export interface ChatMessage {
  id: number;
  session_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface SessionDetail extends ChatSession {
  messages: ChatMessage[];
}

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
