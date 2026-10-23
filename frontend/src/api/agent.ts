// Agent API

import client from "./client";

export interface AgentTool {
  id: number;
  name: string;
  display_name: string;
  description: string;
  params_schema: Record<string, any>;
  enabled: boolean;
  created_at: string;
}

export const agentChat = (data: {
  content: string;
  session_id?: number;
  system_prompt?: string;
  knowledge_base_ids?: number[];
}) =>
  client.post<{
    code: number;
    data: { reply: string; tool_calls: any[]; iterations: number };
  }>("/agent/chat", data);

export const getAgentTools = (enabledOnly = true) =>
  client.get<{ code: number; data: AgentTool[] }>(
    `/agent/tools?enabled_only=${enabledOnly}`
  );

export const toggleAgentTool = (id: number) =>
  client.put<{ code: number; data: AgentTool }>(`/agent/tools/${id}/toggle`);
