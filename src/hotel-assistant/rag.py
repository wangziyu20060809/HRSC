# -*- coding: utf-8 -*-
"""
rag.py — 检索层：加载阶段 1 的 FAISS 索引并提供混合检索

【核心模块 · 全阶段复用】
  直接 import 阶段 1 原型的 HybridRetriever（BM25 + FAISS 向量 + RRF 融合），
  不重写检索逻辑——保证"阶段 1 验证过的检索质量"原样进入 Web 服务。
  索引文件格式与阶段 1 完全一致：rag_index/{chunks.json, vectors.npy}
"""

import json
import sys
from pathlib import Path

import numpy as np

# 把阶段 1 原型目录加入模块搜索路径（仅用于复用其检索核心，不执行其 CLI）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototype"))
from stage1_rag_cli import HybridRetriever  # noqa: E402  （路径插入后才能导入）

INDEX_DIR = Path(__file__).resolve().parent / "rag_index"

_retriever: HybridRetriever | None = None  # 进程内缓存：索引只加载一次


class IndexNotReadyError(RuntimeError):
    """索引未初始化时抛出，接口层转为 40404 中文错误"""


def get_retriever() -> HybridRetriever:
    """惰性加载检索器；索引文件缺失时抛 IndexNotReadyError"""
    global _retriever
    if _retriever is not None:
        return _retriever
    chunks_file = INDEX_DIR / "chunks.json"
    vec_file = INDEX_DIR / "vectors.npy"
    if not (chunks_file.exists() and vec_file.exists()):
        raise IndexNotReadyError("rag_index 不存在，请先运行 ingest.py 入库制度文档")
    data = json.loads(chunks_file.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    vecs = np.load(vec_file)
    _retriever = HybridRetriever(chunks, vecs)
    return _retriever


def reload_retriever() -> None:
    """ingest 重建索引后调用，强制下次请求重新加载"""
    global _retriever
    _retriever = None


def search(question: str, top_k: int = 3) -> list[dict]:
    """
    混合检索入口（供 /chat 与 /ingest 调试使用）。
    返回 [{"clause_no","content","score","rank"}]，按 RRF 分数降序。
    """
    return get_retriever().search(question, top_k=top_k)


def to_citations(hits: list[dict], source_title: str = "", version: str = "") -> list[dict]:
    """
    把检索命中转为前端引用卡所需结构：
    文件名 + 版本 + 条款号 + 原文片段（截取前 120 字）。
    """
    cites = []
    for h in hits:
        cites.append(
            {
                "doc_title": source_title,
                "version": version,
                "clause_no": h.get("clause_no") or f"片段{h['rank'] + 1}",
                "snippet": h["content"][:120],
            }
        )
    return cites
