// Knowledge Base API

import client from "./client";

export interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  doc_count: number;
  created_at: string;
  updated_at: string;
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export const getKnowledgeBases = (page = 1, pageSize = 20) =>
  client.get<{ code: number; data: PaginatedData<KnowledgeBase> }>(
    `/knowledge-bases?page=${page}&page_size=${pageSize}`
  );

export const getKnowledgeBase = (id: number) =>
  client.get<{ code: number; data: KnowledgeBase }>(`/knowledge-bases/${id}`);

export const createKnowledgeBase = (data: { name: string; description?: string }) =>
  client.post<{ code: number; data: KnowledgeBase }>("/knowledge-bases", data);

export const updateKnowledgeBase = (id: number, data: { name?: string; description?: string }) =>
  client.put<{ code: number; data: KnowledgeBase }>(`/knowledge-bases/${id}`, data);

export const deleteKnowledgeBase = (id: number) =>
  client.delete<{ code: number }>(`/knowledge-bases/${id}`);
