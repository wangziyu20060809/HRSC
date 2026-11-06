# -*- coding: utf-8 -*-
"""api/kb_api.py — 知识库管理：文档 CRUD、重建索引、检索测试

写操作限运营管理；检索所有人可用（助手与页面共用同一套检索）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import db, security
from core.errors import ApiError
from kb import store as kb_store

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("/docs")
def docs(user: dict = Depends(security.require_login)):
    items = db.rows("SELECT id, title, category, updated_at, LENGTH(body) AS size FROM kb_docs ORDER BY id")
    return {"code": 0, "docs": items, "stats": kb_store.stats()}


@router.get("/docs/{doc_id}")
def doc(doc_id: int, user: dict = Depends(security.require_login)):
    d = db.row("SELECT * FROM kb_docs WHERE id=?", (doc_id,))
    if not d:
        raise ApiError(40001, "文档不存在")
    chunks = db.rows(
        "SELECT ord, text FROM kb_chunks WHERE doc_id=? ORDER BY ord", (doc_id,)
    )
    return {"code": 0, "doc": d, "chunks": chunks}


class DocBody(BaseModel):
    title: str
    body: str
    category: str = "制度"


@router.post("/docs")
def upsert(body: DocBody, user: dict = Depends(security.require_roles("admin"))):
    if not body.title.strip() or not body.body.strip():
        raise ApiError(40001, "标题与正文不能为空")
    out = kb_store.upsert_doc(body.title.strip(), body.body, body.category)
    db.audit(user["username"], user["role"], "kb:upsert", body.title, f"{out['chunks']} 片")
    return {"code": 0, **out, "message": f"已保存并重建索引（{out['chunks']} 片）"}


@router.delete("/docs/{doc_id}")
def delete(doc_id: int, user: dict = Depends(security.require_roles("admin"))):
    d = db.row("SELECT title FROM kb_docs WHERE id=?", (doc_id,))
    if not d:
        raise ApiError(40001, "文档不存在")
    kb_store.delete_doc(doc_id)
    db.audit(user["username"], user["role"], "kb:delete", d["title"], "")
    return {"code": 0, "message": "已删除"}


@router.post("/reindex")
def reindex(user: dict = Depends(security.require_roles("admin"))):
    out = kb_store.reindex_all()
    db.audit(user["username"], user["role"], "kb:reindex", "", f"{out['docs']} 文档 / {out['chunks']} 片")
    return {"code": 0, **out, "message": f"已重建：{out['docs']} 篇 / {out['chunks']} 片"}


class SearchBody(BaseModel):
    query: str
    top_k: int = 4


@router.post("/search")
def search(body: SearchBody, user: dict = Depends(security.require_login)):
    hits = kb_store.search(body.query, top_k=body.top_k)
    return {"code": 0, "hits": hits, "count": len(hits)}
