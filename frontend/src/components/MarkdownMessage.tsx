// Markdown 渲染（P2-10）—— 回答里经常有列表、表格、代码块，纯文本太亏
//
// 安全说明：react-markdown 默认**不渲染原始 HTML**（没有 dangerouslySetInnerHTML），
// 所以模型输出里的 <script> 之类只会当文本显示。这里再显式关掉 raw HTML 更稳妥。

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body" style={{ fontSize: 14, lineHeight: 1.7 }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // 不启用 rehype-raw：任何 HTML 都按文本转义
        components={{
          p: ({ children }) => <p style={{ margin: "0 0 8px" }}>{children}</p>,
          ul: ({ children }) => (
            <ul style={{ margin: "0 0 8px", paddingLeft: 20 }}>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol style={{ margin: "0 0 8px", paddingLeft: 20 }}>{children}</ol>
          ),
          li: ({ children }) => <li style={{ marginBottom: 2 }}>{children}</li>,
          code: ({ className, children }) => {
            const isBlock = Boolean(className);
            if (isBlock) {
              return (
                <pre
                  style={{
                    background: "#1f1f1f",
                    color: "#e6e6e6",
                    padding: 12,
                    borderRadius: 6,
                    overflowX: "auto",
                    margin: "8px 0",
                  }}
                >
                  <code>{children}</code>
                </pre>
              );
            }
            return (
              <code
                style={{
                  background: "rgba(0,0,0,0.06)",
                  padding: "1px 5px",
                  borderRadius: 4,
                  fontSize: 13,
                }}
              >
                {children}
              </code>
            );
          },
          table: ({ children }) => (
            <div style={{ overflowX: "auto", margin: "8px 0" }}>
              <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th
              style={{
                border: "1px solid #d9d9d9",
                padding: "4px 8px",
                background: "#fafafa",
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td style={{ border: "1px solid #d9d9d9", padding: "4px 8px" }}>
              {children}
            </td>
          ),
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
