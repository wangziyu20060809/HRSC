# -*- coding: utf-8 -*-
"""
kb.py — 制度知识库服务：文档解析、切片向量化、多文档索引、删除重建

索引文件格式（rag_index/）：
  chunks.json  {"docs": {doc_id: {"title","version","chunks":[{clause_no,content,seq}]}}}
  vectors.npy  全部剩余分块的向量（顺序与 docs 遍历顺序一致）

删除文档 = 从 docs 移除该文档 → 对剩余分块重新向量化 → 重写两个文件。
老格式兼容：阶段 2 早期的单文件索引（含 "source" 键）自动包装为 legacy 文档。
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))
from stage1_rag_cli import embed_texts, split_policy  # noqa: E402  复用阶段 1 切片与向量化

INDEX_DIR = Path(__file__).resolve().parent / "rag_index"
CHUNKS_FILE = INDEX_DIR / "chunks.json"
VECTORS_FILE = INDEX_DIR / "vectors.npy"


# =====================================================================
# 索引读写
# =====================================================================
def _load_docs() -> dict:
    """读取索引；兼容老格式与历史双层嵌套，统一返回 {docs:{...}} 结构"""
    if not CHUNKS_FILE.exists():
        return {"docs": {}}
    data = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    # 历史缺陷修复：早期版本曾写出 {"docs":{"docs":{...}}} 双层嵌套，逐层展开
    while isinstance(data, dict) and isinstance(data.get("docs"), dict) \
            and "docs" in data["docs"]:
        data = data["docs"]
    if "docs" in data:
        return data
    # —— 老格式迁移：单文档索引包装为 legacy 文档 ——
    legacy = {
        "title": Path(data.get("source", "legacy")).name or "历史索引",
        "version": "v1.0",
        "chunks": data.get("chunks", []),
    }
    return {"docs": {"legacy": legacy}}


def _save_docs(docs: dict, vectors: np.ndarray | None = None) -> None:
    INDEX_DIR.mkdir(exist_ok=True)
    # 已是 {"docs": ...} 结构则原样写入，避免重复包壳
    payload = docs if isinstance(docs, dict) and "docs" in docs else {"docs": docs}
    CHUNKS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    if vectors is not None:
        np.save(VECTORS_FILE, vectors)


def all_chunks_flat(docs: dict) -> list[dict]:
    """把多文档结构摊平为 [{doc_id,title,version,clause_no,content,seq}]（检索器用）"""
    flat = []
    for doc_id, doc in docs["docs"].items():
        for ch in doc["chunks"]:
            flat.append({
                "doc_id": doc_id,
                "title": doc["title"],
                "version": doc["version"],
                "clause_no": ch.get("clause_no", ""),
                "content": ch["content"],
                "seq": ch.get("seq", 0),
            })
    return flat


# =====================================================================
# 文档解析（markdown / pdf）
# =====================================================================
class ParseError(Exception):
    """文档解析失败（损坏的 PDF 等），接口层转 40010 中文错误"""


def parse_upload(filename: str, content: bytes) -> tuple[str, str]:
    """
    解析上传文件为纯文本。

    :return: (文本内容, 内容哈希)
    :raises ParseError: 不支持的格式或解析失败
    """
    suffix = Path(filename).suffix.lower()
    file_hash = hashlib.md5(content).hexdigest()
    if suffix in (".md", ".markdown", ".txt"):
        return content.decode("utf-8", errors="replace"), file_hash
    if suffix == ".pdf":
        try:
            import io
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if not text.strip():
                raise ParseError("PDF 中未提取到文字，请确认不是扫描件图片")
            return text, file_hash
        except ParseError:
            raise
        except Exception as e:
            raise ParseError(f"PDF 解析失败：{e}")
    raise ParseError(f"不支持的文件格式 {suffix}，仅支持 .md / .txt / .pdf")


# =====================================================================
# 入库与删除
# =====================================================================
def ingest_document(title: str, version: str, text: str,
                    uploaded_by: str = "") -> tuple[str, int]:
    """切片 → 向量化 → 追加进索引；返回 (文档ID, 分块数)"""
    chunks = split_policy(text)
    if not chunks:
        raise ParseError("文档未切出有效内容（需要包含「第X条」条款或正文）")

    docs = _load_docs()
    doc_id = hashlib.md5(f"{title}|{version}|{len(docs['docs'])}".encode()).hexdigest()[:12]
    docs["docs"][doc_id] = {"title": title, "version": version, "chunks": chunks}
    # 全量重建向量：分块量小（数百块），重建成本可忽略，换取逻辑简单
    flat = all_chunks_flat(docs)
    vectors = embed_texts([c["content"] for c in flat])
    _save_docs(docs, vectors)
    return doc_id, len(chunks)


def delete_document(doc_id: str) -> bool:
    """删除文档并重建索引；文档不存在返回 False"""
    docs = _load_docs()
    if doc_id not in docs["docs"]:
        return False
    del docs["docs"][doc_id]
    flat = all_chunks_flat(docs)
    if flat:
        vectors = embed_texts([c["content"] for c in flat])
    else:
        vectors = np.zeros((0, 256), dtype=np.float32)  # 空库占位
    _save_docs(docs, vectors)
    return True


def reindex() -> int:
    """全量重建（管理员的修复手段）；返回当前总分块数"""
    docs = _load_docs()
    flat = all_chunks_flat(docs)
    vectors = embed_texts([c["content"] for c in flat]) if flat else np.zeros((0, 256), dtype=np.float32)
    _save_docs(docs, vectors)
    return len(flat)
