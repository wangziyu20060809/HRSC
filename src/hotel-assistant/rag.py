# -*- coding: utf-8 -*-
"""
rag.py — 检索层：加载本地索引并提供混合检索

【核心模块 · 全阶段复用】
  检索器本体仍是阶段 1 的 HybridRetriever（BM25 + FAISS + RRF 融合）；
  索引加载改为读取 kb.py 的多文档结构（chunks.json {docs:{...}}），
  命中结果自动携带 doc_id / title / version，供引用卡展示。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))
from stage1_rag_cli import HybridRetriever  # noqa: E402  路径插入后才能导入

import kb  # noqa: E402  多文档索引结构（同目录）

_retriever: HybridRetriever | None = None  # 进程内缓存


class IndexNotReadyError(RuntimeError):
    """索引未初始化时抛出，接口层转为 40404 中文错误"""


def get_retriever() -> HybridRetriever:
    """惰性加载检索器；索引为空时抛 IndexNotReadyError"""
    global _retriever
    if _retriever is not None:
        return _retriever
    docs = kb._load_docs()
    chunks = kb.all_chunks_flat(docs)
    if not chunks:
        raise IndexNotReadyError("rag_index 为空，请先入库制度文档")
    vectors = np.load(kb.VECTORS_FILE) if kb.VECTORS_FILE.exists() else None
    if vectors is None or vectors.shape[0] != len(chunks):
        # 索引文件与元数据不一致（异常中断导致）：自动重建
        vectors = kb.reindex()
    _retriever = HybridRetriever(chunks, vectors)
    return _retriever


def reload_retriever() -> None:
    """知识库变更（上传/删除）后调用，强制下次请求重新加载"""
    global _retriever
    _retriever = None


def search(question: str, top_k: int = 3) -> list[dict]:
    """混合检索入口；返回含 doc_id/title/version 的命中列表"""
    return get_retriever().search(question, top_k=top_k)
