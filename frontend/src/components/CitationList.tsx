// 引用卡片（P2-10）—— 让用户能确认"这句话是哪来的"
//
// 数据来自后端 SSE 的 `event: rag`：
//   {context_length, citations: [{document_id, document_name, chunk_index, similarity, snippet}]}

import { Collapse, Empty, Tag, Typography } from "antd";
import { FileTextOutlined } from "@ant-design/icons";

import type { Citation } from "../api/chat";

const { Text } = Typography;

export default function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations || citations.length === 0) return null;

  return (
    <Collapse
      size="small"
      style={{ marginTop: 12, background: "#fafafa" }}
      items={[
        {
          key: "citations",
          label: (
            <Text type="secondary" style={{ fontSize: 12 }}>
              <FileTextOutlined /> 引用 {citations.length} 条资料
            </Text>
          ),
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {citations.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                citations.map((citation) => (
                  <div
                    key={`${citation.document_id}-${citation.chunk_index}`}
                    style={{
                      background: "#fff",
                      border: "1px solid #f0f0f0",
                      borderRadius: 6,
                      padding: "8px 10px",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 8,
                        marginBottom: 4,
                      }}
                    >
                      <Text strong style={{ fontSize: 13 }}>
                        {citation.document_name}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {" "}
                          第 {(citation.chunk_index ?? 0) + 1} 段
                        </Text>
                      </Text>
                      <Tag color={citation.similarity >= 0.7 ? "green" : "default"}>
                        相关度 {citation.similarity.toFixed(2)}
                      </Tag>
                    </div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {citation.snippet}
                      {citation.snippet.length >= 160 ? "…" : ""}
                    </Text>
                  </div>
                ))
              )}
            </div>
          ),
        },
      ]}
    />
  );
}
