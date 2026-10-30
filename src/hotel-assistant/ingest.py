# -*- coding: utf-8 -*-
"""
ingest.py — 制度文档入库：切片 → 向量化 → 写本地 FAISS 索引

复用阶段 1 的 split_policy / embed_texts（核心模块原样复用），
索引写入本目录 rag_index/（格式与阶段 1 一致，rag.py 直接加载）。

用法：
    python ingest.py                          # 默认入库 data/差旅报销管理办法.md
    python ingest.py data/其他制度.md
"""

import json
import sys
from pathlib import Path

import numpy as np

# 复用阶段 1 原型的切片与向量化（不重复实现）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))
from stage1_rag_cli import embed_texts, split_policy  # noqa: E402

INDEX_DIR = Path(__file__).resolve().parent / "rag_index"


def ingest(md_path: str) -> None:
    doc = Path(md_path)
    if not doc.exists():
        print(f"[错误] 文件不存在：{doc}")
        sys.exit(1)

    text = doc.read_text(encoding="utf-8")
    chunks = split_policy(text)
    if not chunks:
        print("[错误] 未切出内容，请检查文档")
        sys.exit(1)
    print(f"[切片] {doc.name} → {len(chunks)} 块")

    vecs = embed_texts([c["content"] for c in chunks])
    print(f"[向量化] {len(chunks)} 块 × {vecs.shape[1]} 维")

    INDEX_DIR.mkdir(exist_ok=True)
    np.save(INDEX_DIR / "vectors.npy", vecs)
    (INDEX_DIR / "chunks.json").write_text(
        json.dumps(
            {"source": str(doc), "chunk_count": len(chunks), "chunks": chunks},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[完成] 索引已保存到 {INDEX_DIR}/")


if __name__ == "__main__":
    ingest(sys.argv[1] if len(sys.argv) > 1 else "data/客房管理制度.md")
