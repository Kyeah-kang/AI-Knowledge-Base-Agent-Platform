// 聊天状态管理

import { create } from "zustand";
import type { ChatMessage, ChatSession } from "../api/chat";

interface ChatState {
  sessions: ChatSession[];
  currentSessionId: number | null;
  messages: ChatMessage[];
  isStreaming: boolean;

  setSessions: (sessions: ChatSession[]) => void;
  setCurrentSession: (id: number) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  setIsStreaming: (v: boolean) => void;
  appendToLastMessage: (token: string) => void;
  /** 给最后一条消息补字段（例如把引用挂到回答上） */
  patchLastMessage: (patch: Partial<ChatMessage>) => void;
  /** 移除最后一条消息（重试时先把失败的回答去掉） */
  removeLastMessage: () => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  currentSessionId: null,
  messages: [],
  isStreaming: false,

  setSessions: (sessions) => set({ sessions }),

  setCurrentSession: (id) => set({ currentSessionId: id }),

  setMessages: (messages) => set({ messages }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  setIsStreaming: (v) => set({ isStreaming: v }),

  appendToLastMessage: (token) => {
    const messages = get().messages;
    if (messages.length === 0) return;
    const last = messages[messages.length - 1];
    last.content += token;
    set({ messages: [...messages] });
  },

  patchLastMessage: (patch) => {
    const messages = get().messages;
    if (messages.length === 0) return;
    const last = { ...messages[messages.length - 1], ...patch };
    set({ messages: [...messages.slice(0, -1), last] });
  },

  removeLastMessage: () => {
    const messages = get().messages;
    if (messages.length === 0) return;
    set({ messages: messages.slice(0, -1) });
  },

  reset: () => set({ messages: [], currentSessionId: null }),
}));
