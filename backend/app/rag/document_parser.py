"""
文档解析器 — 从不同格式文件中提取纯文本

支持格式：
  - PDF   → pypdf2
  - DOCX  → python-docx
  - MD    → 按行读取（Markdown 本质是纯文本 + 格式标记）
  - TXT   → 按行读取

用法：
    parser = DocumentParser()
    text = await parser.parse(file_path, file_type)  # "pdf" / "docx" / "md" / "txt"

每个解析方法都返回提取后的纯文本字符串。
如果解析失败，抛出 AppException(400)，由全局异常处理器统一处理。
"""

import traceback

from app.core.exceptions import AppException


class DocumentParser:
    """
    文档解析器

    根据文件类型分发到具体的解析方法。
    新增文件类型只需要在 _parsers 字典中注册即可。
    """

    def __init__(self):
        # 解析器注册表 — 文件类型 → 解析方法
        # 新增格式只需在这里加一条映射
        self._parsers = {
            "pdf": self._parse_pdf,
            "docx": self._parse_docx,
            "md": self._parse_text,      # Markdown 当作纯文本处理
            "txt": self._parse_text,
            "html": self._parse_text,    # HTML 也当作纯文本（简单处理）
        }

    async def parse(self, file_path: str, file_type: str) -> str:
        """
        解析文档，返回纯文本内容。

        参数：
            file_path: 文件在磁盘上的完整路径
            file_type: 文件类型（pdf / docx / md / txt / html）

        返回：
            提取后的纯文本字符串

        异常：
            AppException(400) — 不支持的格式或解析失败
        """
        parser = self._parsers.get(file_type.lower())
        if not parser:
            raise AppException(
                code=400,
                message=f"不支持的文档格式：{file_type}",
                http_status_code=400,
            )

        try:
            return parser(file_path)
        except AppException:
            raise
        except Exception as e:
            raise AppException(
                code=400,
                message=f"文档解析失败：{str(e)}",
                http_status_code=400,
                detail=traceback.format_exc(),
            )

    # ─── PDF 解析 ───

    def _parse_pdf(self, file_path: str) -> str:
        """使用 pypdf2 提取 PDF 文本内容"""
        from PyPDF2 import PdfReader
        # 打开PDF文件
        reader = PdfReader(file_path)
        # 准备一个列表，用来保存每一页提取出来的文本
        pages = []

        # 逐页读取 PDF
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if text.strip():
                pages.append(f"--- 第 {page_num + 1} 页 ---\n{text}")

        # 把所有页的文本合并成一个大字符串
        result = "\n\n".join(pages)
        if not result.strip():
            raise AppException(
                code=400,
                message="PDF 文件未能提取出任何文本内容（可能是扫描件或图片型PDF）",
                http_status_code=400,
            )
        return result

    # ─── Word 解析 ───

    def _parse_docx(self, file_path: str) -> str:
        """使用 python-docx 提取 Word 文本内容"""
        from docx import Document as DocxDocument

        doc = DocxDocument(file_path)
        paragraphs = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)

        result = "\n\n".join(paragraphs)
        if not result.strip():
            raise AppException(
                code=400,
                message="Word 文件未能提取出任何文本内容",
                http_status_code=400,
            )
        return result

    # ─── 纯文本解析（MD / TXT / HTML） ───

    def _parse_text(self, file_path: str) -> str:
        """读取纯文本文件内容"""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        if not text.strip():
            raise AppException(
                code=400,
                message="文件内容为空",
                http_status_code=400,
            )
        return text
