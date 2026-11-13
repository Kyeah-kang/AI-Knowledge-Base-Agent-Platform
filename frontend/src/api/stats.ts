// 统计 API（P2-9）—— Dashboard 的数字必须来自后端，不能写死

import client from "./client";

export interface StatsOverview {
  kb_count: number;
  doc_count: number;
  failed_doc_count: number;
  session_count: number;
  message_count: number;
}

export const getOverview = () =>
  client.get<{ code: number; data: StatsOverview }>("/stats/overview");
