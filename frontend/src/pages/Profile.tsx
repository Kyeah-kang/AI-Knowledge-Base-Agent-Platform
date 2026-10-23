import { useEffect, useState } from "react";
import { Card, Form, Input, Button, Typography, message, Descriptions, Tag, Avatar } from "antd";
import { UserOutlined } from "@ant-design/icons";
import { updateProfile } from "../api/user";
import { useAuthStore } from "../store/authStore";

const { Title } = Typography;

export default function Profile() {
  const { user, setUser } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({ username: user?.username, email: user?.email || "" });
  }, [user]);

  const handleSave = async (values: { username: string; email?: string }) => {
    setLoading(true);
    try {
      const res = await updateProfile(values);
      setUser(res.data.data);
      message.success("更新成功");
    } catch (err: any) {
      message.error(err.response?.data?.message || "更新失败");
    } finally {
      setLoading(false);
    }
  };

  if (!user) return null;

  return (
    <div style={{ maxWidth: 600, margin: "0 auto" }}>
      <Title level={4}>个人中心</Title>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <Avatar size={80} icon={<UserOutlined />} />
          <div style={{ marginTop: 8 }}>
            <Tag color={user.is_admin ? "red" : "blue"}>
              {user.is_admin ? "管理员" : "普通用户"}
            </Tag>
          </div>
        </div>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="用户 ID">{(user as any).id}</Descriptions.Item>
          <Descriptions.Item label="用户名">{user.username}</Descriptions.Item>
          <Descriptions.Item label="邮箱">{user.email || "未设置"}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="编辑资料">
        <Form form={form} layout="vertical" onFinish={handleSave}>
          <Form.Item name="username" label="用户名"><Input /></Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
            <Input />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>保存</Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
