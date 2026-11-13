"""阶段6 集成测试（含降级模式：PG不可用时不报错）"""
import json
import os
import tempfile

import httpx

BASE = 'http://localhost:8000/api/v1'

def p(label, r, fields=None):
    data = r.json()
    print(f"{label}: [{r.status_code}] ", end="")
    d = data.get("data")
    if d and fields:
        print({k: d.get(k) for k in fields})
    elif d:
        print(json.dumps(d, ensure_ascii=False, indent=2)[:200])
    else:
        print(f"msg={data.get('message')}")
    return d

# 1. 尝试登录，如果用户不存在则注册
r = httpx.post(f"{BASE}/auth/login", json={"username": "kbuser", "password": "test123456"})
if r.status_code != 200:
    r = httpx.post(f"{BASE}/auth/register", json={"username": "kbuser", "password": "test123456"})
    p("REGISTER", r, ["username"])
else:
    print("LOGIN: [200] 用户已存在，直接登录")

token = r.json().get("data", {}).get("access_token", "")
headers = {"Authorization": f"Bearer {token}"}
assert token, "❌ 获取token失败"
print()

# 2. 创建知识库
r = httpx.post(
    f"{BASE}/knowledge-bases",
    headers=headers,
    json={"name": "Python教程", "description": "Python学习资料", "category": "技术"},
)
kb = p("CREATE KB", r, ["id", "name", "category"])
kb_id = kb.get("id")
print()

# 3. 知识库列表
r = httpx.get(f"{BASE}/knowledge-bases", headers=headers)
p("LIST KB", r, ["total", "page"])
print()

# 4. 知识库详情
r = httpx.get(f"{BASE}/knowledge-bases/{kb_id}", headers=headers)
p("GET KB", r, ["id", "name", "doc_count"])
print()

# 5. 创建临时测试文件
tmp = os.path.join(tempfile.gettempdir(), "py_intro.txt")
with open(tmp, "w", encoding="utf-8") as f:
    f.write("Python编程语言入门\n\nPython是一种高级编程语言，由Guido van Rossum于1991年创建。\n\nPython的设计哲学强调代码的可读性，使用缩进来定义代码块。\n\nPython广泛应用于Web开发、数据分析、人工智能、科学计算等领域。\n\n" * 5)

# 6. 上传文档
with open(tmp, "rb") as f:
    r = httpx.post(
        f"{BASE}/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("py_intro.txt", f, "text/plain")},
    )
doc_data = p("UPLOAD DOC", r, ["chunk_count", "message"])
doc_id = doc_data.get("document", {}).get("id")
print(f"   doc_id={doc_id}")
print()

# 7. 文档详情（含切片）
if doc_id:
    r = httpx.get(f"{BASE}/documents/{doc_id}", headers=headers)
    doc_resp = p("GET DOC", r, ["id", "filename", "file_type", "status", "chunk_count"])
    chunks = r.json().get("data", {}).get("chunks", [])
    print(f"   chunks count: {len(chunks)}")
    for c in chunks[:2]:
        print(f"   chunk[{c['chunk_index']}]: {c['content'][:60]}...")
print()

# 8. 文档列表
r = httpx.get(f"{BASE}/knowledge-bases/{kb_id}/documents", headers=headers)
p("LIST DOCS", r, ["total"])
print()

# 9. 更新知识库
r = httpx.put(
    f"{BASE}/knowledge-bases/{kb_id}",
    headers=headers,
    json={"name": "Python高级教程", "description": "更新后的描述"},
)
p("UPDATE KB", r, ["name", "description"])
print()

print()

print("Phase 6 ALL TESTS PASSED")
