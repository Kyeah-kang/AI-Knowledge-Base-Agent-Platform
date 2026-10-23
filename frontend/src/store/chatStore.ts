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

  reset: () => set({ messages: [], currentSessionId: null }),
}));
