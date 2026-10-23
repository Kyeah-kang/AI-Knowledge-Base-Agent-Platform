import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Table, Button, Modal, Form, Input, Card, Typography, Space, Popconfirm, message, Tag,
} from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, FileOutlined } from "@ant-design/icons";
import {
  getKnowledgeBases, createKnowledgeBase, updateKnowledgeBase, deleteKnowledgeBase,
} from "../api/knowledgeBase";
import type { KnowledgeBase } from "../api/knowledgeBase";
import { DEFAULT_PAGE_SIZE } from "../utils/constants";

const { Title } = Typography;

export default function KnowledgeBaseList() {
  const navigate = useNavigate();
  const [data, setData] = useState<KnowledgeBase[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeBase | null>(null);
  const [form] = Form.useForm();

  const fetchData = async (p = 1) => {
    setLoading(true);
    try {
      const res = await getKnowledgeBases(p, DEFAULT_PAGE_SIZE);
      setData(res.data.data.items);
      setTotal(res.data.data.total);
      setPage(p);
    } catch {
      message.error("加载知识库失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleEdit = (kb: KnowledgeBase) => {
    setEditing(kb);
    form.setFieldsValue(kb);
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    try {
      if (editing) {
        await updateKnowledgeBase(editing.id, values);
        message.success("更新成功");
      } else {
        await createKnowledgeBase(values);
        message.success("创建成功");
      }
      setModalOpen(false);
      fetchData(page);
    } catch (err: any) {
      message.error(err.response?.data?.message || "操作失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteKnowledgeBase(id);
      message.success("删除成功");
      fetchData(page);
    } catch { message.error("删除失败"); }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "名称", dataIndex: "name", key: "name", ellipsis: true },
    { title: "描述", dataIndex: "description", key: "description", ellipsis: true },
    { title: "文档数", dataIndex: "doc_count", key: "doc_count", width: 80, render: (c: number) => <Tag color="blue">{c}</Tag> },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 170, render: (t: string) => new Date(t).toLocaleString("zh-CN") },
    {
      title: "操作", key: "action", width: 200,
      render: (_: any, record: KnowledgeBase) => (
        <Space>
          <Button type="link" icon={<FileOutlined />} onClick={() => navigate(`/knowledge-bases/${record.id}/documents`)}>文档</Button>
          <Button type="link" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>知识库管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建知识库</Button>
      </div>
      <Card>
        <Table
          dataSource={data} columns={columns} rowKey="id" loading={loading}
          pagination={{ current: page, total, pageSize: DEFAULT_PAGE_SIZE, onChange: fetchData, showTotal: (t) => `共 ${t} 个知识库` }}
        />
      </Card>
      <Modal title={editing ? "编辑知识库" : "新建知识库"} open={modalOpen} onOk={handleSave} onCancel={() => setModalOpen(false)} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="知识库名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="知识库描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
