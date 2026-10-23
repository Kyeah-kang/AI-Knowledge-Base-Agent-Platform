import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Table, Button, Upload, Card, Typography, Space, Popconfirm, message, Tag, Modal, List,
} from "antd";
import { UploadOutlined, DeleteOutlined, EyeOutlined, ArrowLeftOutlined } from "@ant-design/icons";
import { getDocuments, uploadDocument, deleteDocument, getDocumentDetail } from "../api/document";
import { getKnowledgeBase } from "../api/knowledgeBase";
import type { Document, DocumentChunk } from "../api/document";
import { DEFAULT_PAGE_SIZE, ALLOWED_EXTENSIONS } from "../utils/constants";

const { Title } = Typography;

export default function DocumentList() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [kbName, setKbName] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<any>(null);
  const [previewChunks, setPreviewChunks] = useState<DocumentChunk[]>([]);

  const fetchData = async (p = 1) => {
    if (!kbId) return;
    setLoading(true);
    try {
      const [kbRes, docRes] = await Promise.all([
        getKnowledgeBase(Number(kbId)),
        getDocuments(Number(kbId), p, DEFAULT_PAGE_SIZE),
      ]);
      setKbName(kbRes.data.data.name);
      setData(docRes.data.data.items);
      setTotal(docRes.data.data.total);
      setPage(p);
    } catch { message.error("加载文档失败"); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, [kbId]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      await uploadDocument(Number(kbId), file);
      message.success("上传成功");
      fetchData(page);
    } catch (err: any) { message.error(err.response?.data?.message || "上传失败"); }
    finally { setUploading(false); }
    return false;
  };

  const handleDelete = async (docId: number) => {
    try { await deleteDocument(docId); message.success("删除成功"); fetchData(page); }
    catch { message.error("删除失败"); }
  };

  const handlePreview = async (docId: number) => {
    try {
      const res = await getDocumentDetail(docId);
      setPreviewDoc(res.data.data);
      setPreviewChunks(res.data.data.chunks || []);
      setPreviewOpen(true);
    } catch { message.error("加载文档详情失败"); }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const statusColor: Record<string, string> = { completed: "green", processing: "blue", pending: "orange", failed: "red" };

  const columns = [
    { title: "文件名", dataIndex: "filename", key: "filename", ellipsis: true },
    { title: "类型", dataIndex: "file_type", key: "file_type", width: 80, render: (t: string) => <Tag>{t.toUpperCase()}</Tag> },
    { title: "大小", dataIndex: "file_size", key: "file_size", width: 100, render: (s: number) => formatSize(s) },
    { title: "状态", dataIndex: "status", key: "status", width: 100, render: (s: string) => <Tag color={statusColor[s] || "default"}>{s}</Tag> },
    { title: "切片数", dataIndex: "chunk_count", key: "chunk_count", width: 80, render: (c: number) => c || "-" },
    { title: "上传时间", dataIndex: "created_at", key: "created_at", width: 170, render: (t: string) => new Date(t).toLocaleString("zh-CN") },
    {
      title: "操作", key: "action", width: 160,
      render: (_: any, record: Document) => (
        <Space>
          <Button type="link" icon={<EyeOutlined />} onClick={() => handlePreview(record.id)}>预览</Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16, alignItems: "center" }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/knowledge-bases")} />
          <Title level={4} style={{ margin: 0 }}>{kbName} - 文档管理</Title>
        </Space>
        <Upload beforeUpload={handleUpload} showUploadList={false} accept={ALLOWED_EXTENSIONS.join(",")} disabled={uploading}>
          <Button type="primary" icon={<UploadOutlined />} loading={uploading}>上传文档</Button>
        </Upload>
      </div>
      <Card>
        <Table
          dataSource={data} columns={columns} rowKey="id" loading={loading}
          pagination={{ current: page, total, pageSize: DEFAULT_PAGE_SIZE, onChange: fetchData, showTotal: (t) => `共 ${t} 个文档` }}
        />
      </Card>
      <Modal title={previewDoc?.filename || "文档预览"} open={previewOpen} onCancel={() => setPreviewOpen(false)} footer={null} width={800}>
        {previewChunks.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, color: "#999" }}>暂无切片内容（文档可能正在处理中）</div>
        ) : (
          <List
            dataSource={previewChunks}
            renderItem={(chunk: DocumentChunk) => (
              <List.Item>
                <div style={{ width: "100%" }}>
                  <Tag color="blue">切片 #{chunk.chunk_index}</Tag>
                  <div style={{ marginTop: 8, padding: 12, background: "#f5f5f5", borderRadius: 6, whiteSpace: "pre-wrap", fontSize: 13, maxHeight: 200, overflow: "auto" }}>
                    {chunk.content}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </div>
  );
}
