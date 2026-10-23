// 全局常量

export const APP_NAME = "AI 知识库 Agent 平台";

export const FILE_SIZE_LIMIT_MB = 50;
export const FILE_SIZE_LIMIT_BYTES = FILE_SIZE_LIMIT_MB * 1024 * 1024;

export const ALLOWED_FILE_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/markdown",
  "text/plain",
  "text/html",
];
export const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".md", ".txt", ".html"];

export const CHAT_PAGE_SIZE = 20;
export const DEFAULT_PAGE_SIZE = 20;
