// Document API

import client from "./client";
import type { PaginatedData } from "./knowledgeBase";

export interface Document {
  id: number;
  knowledge_base_id: number;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  chunk_count: number;
  created_at: string;
}

export interface DocumentChunk {
  id: number;
  document_id: number;
  chunk_index: number;
  content: string;
  created_at: string;
}

export interface DocumentDetail extends Document {
  chunks: DocumentChunk[];
}

export const uploadDocument = (kbId: number, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return client.post<{ code: number; data: any }>(
    `/knowledge-bases/${kbId}/documents`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
};

export const getDocuments = (kbId: number, page = 1, pageSize = 20) =>
  client.get<{ code: number; data: PaginatedData<Document> }>(
    `/knowledge-bases/${kbId}/documents?page=${page}&page_size=${pageSize}`
  );

export const getDocumentDetail = (docId: number) =>
  client.get<{ code: number; data: DocumentDetail }>(`/documents/${docId}`);

export const deleteDocument = (docId: number) =>
  client.delete<{ code: number }>(`/documents/${docId}`);
