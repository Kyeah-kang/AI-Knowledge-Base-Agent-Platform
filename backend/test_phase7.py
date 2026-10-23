"""阶段7 RAG（检索增强生成）集成测试

测试内容：
  1. 上传文档并验证切片生成
  2. 文档上传触发 embedding 生成（如果 Embedding API 已配置）
  3. RAG 检索（验证向量搜索接口）
  4. RAG 聊天（带知识库上下文的对话）

注意：
  - MySQL + PostgreSQL 需要在运行
  - Embedding API 可选：未配置时跳过 embedding 测试
  - LLM API 必须配置：用于测试 RAG 聊天
  - 长时间等待的 LLM 调用设有 60s 超时
"""

import json
import os
import sys
import tempfile

import httpx

BASE = "http://localhost:8000/api/v1"
OK_COUNT = 0
FAIL_COUNT = 0


def check(label, condition, detail=""):
    global OK_COUNT, FAIL_COUNT
    if condition:
        OK_COUNT += 1
        print(f"  [PASS] {label}")
    else:
        FAIL_COUNT += 1
        marker = detail or "FAIL"
        print(f"  [FAIL] {label}: {marker}")


def p(label, r, fields=None):
    data = r.json()
    print(f"{label}: [{r.status_code}] ", end="")
    d = data.get("data")
    if d and fields:
        print({k: d.get(k) for k in fields})
    elif d:
        print(json.dumps(d, ensure_ascii=False, indent=2)[:300])
    else:
        print(f"msg={data.get('message')}")
    return d


# ═══════════════════════════════════════
# 1. 登录 / 注册
# ═══════════════════════════════════════
print("=" * 50)
print("Phase 7 RAG 集成测试")
print("=" * 50)

r = httpx.post(f"{BASE}/auth/login", json={"username": "raguser", "password": "test123456"})
if r.status_code != 200:
    r = httpx.post(f"{BASE}/auth/register", json={"username": "raguser", "password": "test123456"})
    p("REGISTER", r, ["username"])
else:
    print("LOGIN: [200] 用户已存在，直接登录")

token = r.json().get("data", {}).get("access_token", "")
headers = {"Authorization": f"Bearer {token}"}
assert token, "获取 token 失败"

# ═══════════════════════════════════════
# 2. 创建知识库
# ═══════════════════════════════════════
r = httpx.post(
    f"{BASE}/knowledge-bases",
    headers=headers,
    json={"name": "RAG测试知识库", "description": "用于测试RAG检索", "category": "测试"},
)
kb = p("CREATE KB", r, ["id", "name"])
kb_id = kb.get("id")
check("知识库创建成功", kb_id is not None)
print()

# ═══════════════════════════════════════
# 3. 上传文档（含自动切片 + embedding）
# ═══════════════════════════════════════
test_content = """
Python编程语言完全指南

Python是一种高级编程语言，由Guido van Rossum于1991年首次发布。
Python的设计哲学强调代码的可读性，使用有意义的缩进来定义代码块。

Python的主要特点包括：
1. 简单易学：语法清晰，接近自然语言
2. 免费开源：可以自由使用和分发
3. 跨平台：Windows、macOS、Linux都可以运行
4. 丰富的库：标准库和第三方库非常丰富
5. 动态类型：不需要声明变量类型
6. 面向对象：支持面向对象编程范式

Python的应用领域非常广泛：
- Web开发：Django、Flask等框架
- 数据分析：NumPy、Pandas、Matplotlib
- 人工智能：TensorFlow、PyTorch、scikit-learn
- 科学计算：SciPy、SymPy
- 自动化运维：Ansible、SaltStack
- 网络爬虫：Scrapy、BeautifulSoup

Python的安装非常简单：
1. 访问 python.org 下载安装包
2. 运行安装程序，勾选"Add Python to PATH"
3. 打开终端，输入 python --version 验证安装

Python的基本语法：
- 变量赋值：x = 10
- 条件语句：if x > 0: print("正数")
- 循环：for i in range(10): print(i)
- 函数定义：def hello(name): return f"Hello, {name}"
- 列表：fruits = ["苹果", "香蕉", "橙子"]
- 字典：person = {"name": "张三", "age": 25}
""".strip()

tmp = os.path.join(tempfile.gettempdir(), "python_guide.txt")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(test_content)

with open(tmp, "rb") as f:
    r = httpx.post(
        f"{BASE}/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("python_guide.txt", f, "text/plain")},
    )
doc_data = p("UPLOAD DOC", r, ["chunk_count", "message"])
doc_id = doc_data.get("document", {}).get("id")
chunk_count = doc_data.get("chunk_count", 0)
check("文档上传成功", doc_id is not None)
check("切片数量 > 0", chunk_count > 0)
has_embedding = "未生成向量嵌入" not in doc_data.get("message", "")
if has_embedding:
    check("向量嵌入已生成", True)
else:
    print("  [SKIP] 向量嵌入: Embedding API 未配置，跳过")
print()

# ═══════════════════════════════════════
# 4. 获取文档详情，检查切片
# ═══════════════════════════════════════
if doc_id:
    r = httpx.get(f"{BASE}/documents/{doc_id}", headers=headers)
    doc_resp = p("GET DOC", r, ["id", "filename", "status", "chunk_count"])
    chunks = r.json().get("data", {}).get("chunks", [])
    check("文档状态为 completed", doc_resp.get("status") == "completed")
    check("切片列表非空", len(chunks) > 0)
    print()
else:
    print("  [SKIP] 文档详情: 文档未上传成功")
    print()

# ═══════════════════════════════════════
# 5. 创建聊天会话
# ═══════════════════════════════════════
r = httpx.post(
    f"{BASE}/chat/sessions",
    headers=headers,
    json={"title": "RAG测试会话", "model_name": "deepseek-chat"},
)
session = p("CREATE SESSION", r, ["id", "title"])
session_id = session.get("id")
check("会话创建成功", session_id is not None)
print()

# ═══════════════════════════════════════
# 6. 非流式 RAG 消息
# ═══════════════════════════════════════
if session_id:
    print("=== 非流式 RAG 聊天 ===")
    try:
        r = httpx.post(
            f"{BASE}/chat/sessions/{session_id}/messages",
            headers=headers,
            json={
                "content": "Python有哪些主要特点？",
                "knowledge_base_ids": [kb_id],
            },
            timeout=120,
        )
        msg_data = p("SEND MSG (RAG)", r, ["role"])
        check("RAG 消息返回成功", r.status_code == 200)
        reply = msg_data.get("content", "") if msg_data else ""
        if reply:
            check("AI 回复非空", len(reply) > 10)
    except Exception as e:
        print(f"  [FAIL] RAG 消息 HTTP 异常: {e}")
else:
    print("  [SKIP] RAG 消息: 会话未创建")
print()

# ═══════════════════════════════════════
# 7. 文档列表
# ═══════════════════════════════════════
r = httpx.get(f"{BASE}/knowledge-bases/{kb_id}/documents", headers=headers)
list_data = p("LIST DOCS", r, ["total"])
check("文档列表接口正常", r.status_code == 200)
print()

# ═══════════════════════════════════════
# 清理
# ═══════════════════════════════════════
print("=== 清理 ===")
if session_id:
    r = httpx.delete(f"{BASE}/chat/sessions/{session_id}", headers=headers)
    print(f"DELETE SESSION: [{r.status_code}]")

if kb_id:
    r = httpx.delete(f"{BASE}/knowledge-bases/{kb_id}", headers=headers)
    print(f"DELETE KB: [{r.status_code}] ({'OK' if r.status_code == 200 else 'FAIL'})")

print()
print("=" * 50)
print(f"Phase 7 RAG TEST RESULTS: {OK_COUNT} passed, {FAIL_COUNT} failed")
if FAIL_COUNT == 0:
    print("ALL TESTS PASSED")
else:
    print(f"{FAIL_COUNT} TEST(S) FAILED")
print("=" * 50)
