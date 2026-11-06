# -*- coding: utf-8 -*-
"""kb/store.py — 知识库：切片、索引、混合检索

链路：文档 → 按段落切片（≤320 字，40 字重叠）→ 分词 + 哈希向量 → 落库
检索：BM25（字面）+ 余弦（向量）→ RRF 融合 → top_k 带引用返回

为什么两路都要：BM25 对「已清扫≠可售」这种精确术语最准；向量对「客人到了房间还没好」这种
口语化问法有补位作用。RRF 不需要调权重，两路各自排序后取倒数排名和即可。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from core import db
from kb.embedder import DIM, dot, embed, pack, tokenize, unpack

MAX_CHARS = 320
OVERLAP = 40
DOC_DIR = Path(__file__).resolve().parent / "docs"

_CACHE: dict | None = None


# ---------------------------------------------------------------------
# 切片与入库
# ---------------------------------------------------------------------
def chunk_text(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(p) > MAX_CHARS:
            if buf:
                chunks.append(buf)
                buf = ""
            start = 0
            while start < len(p):
                chunks.append(p[start : start + MAX_CHARS])
                start += MAX_CHARS - OVERLAP
            continue
        if len(buf) + len(p) + 1 <= MAX_CHARS:
            buf = f"{buf}\n{p}".strip()
        else:
            chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks


def _index_doc(conn, doc_id: int, body: str) -> int:
    conn.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
    for i, ch in enumerate(chunk_text(body)):
        conn.execute(
            "INSERT INTO kb_chunks(doc_id, ord, text, tokens, vec) VALUES(?,?,?,?,?)",
            (doc_id, i, ch, " ".join(tokenize(ch)), pack(embed(ch))),
        )
    return i + 1 if body.strip() else 0


def upsert_doc(title: str, body: str, category: str = "制度") -> dict:
    now = db.now_str()
    existing = db.row("SELECT * FROM kb_docs WHERE title=?", (title,))
    if existing:
        db.exec_write(
            "UPDATE kb_docs SET body=?, category=?, updated_at=? WHERE id=?",
            (body, category, now, existing["id"]),
        )
        doc_id = existing["id"]
    else:
        doc_id = db.exec_write(
            "INSERT INTO kb_docs(title, category, body, updated_at) VALUES(?,?,?,?)",
            (title, category, body, now),
        )
    with db.connect() as conn:
        n = _index_doc(conn, doc_id, body)
    invalidate()
    return {"id": doc_id, "title": title, "chunks": n}


def delete_doc(doc_id: int) -> None:
    db.exec_write("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
    db.exec_write("DELETE FROM kb_docs WHERE id=?", (doc_id,))
    invalidate()


def reindex_all() -> dict:
    docs = db.rows("SELECT * FROM kb_docs")
    total = 0
    with db.connect() as conn:
        for d in docs:
            total += _index_doc(conn, d["id"], d["body"])
    invalidate()
    return {"docs": len(docs), "chunks": total}


def seed_from_files() -> int:
    """把 kb/docs/*.md 载入知识库（幂等：同名文档覆盖正文）"""
    if not DOC_DIR.exists():
        return 0
    n = 0
    for path in sorted(DOC_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = path.stem
        category = "制度"
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("# "):
            head = lines[0][2:].strip()
            if "——" in head:
                title, category = [x.strip() for x in head.split("——", 1)]
            else:
                title = head
        upsert_doc(title, text, category)
        n += 1
    return n


# ---------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------
def invalidate() -> None:
    global _CACHE
    _CACHE = None


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    docs = {d["id"]: d for d in db.rows("SELECT * FROM kb_docs")}
    chunks = db.rows("SELECT * FROM kb_chunks ORDER BY doc_id, ord")
    items = []
    for c in chunks:
        toks = c["tokens"].split()
        items.append(
            {
                "id": c["id"],
                "doc_id": c["doc_id"],
                "ord": c["ord"],
                "text": c["text"],
                "tokens": toks,
                "tf": _tf(toks),
                "len": len(toks),
                "vec": unpack(c["vec"]) if c["vec"] else [0.0] * DIM,
                "title": docs.get(c["doc_id"], {}).get("title", "未命名"),
                "category": docs.get(c["doc_id"], {}).get("category", ""),
            }
        )
    avgdl = (sum(i["len"] for i in items) / len(items)) if items else 0
    df: dict[str, int] = {}
    for it in items:
        for t in set(it["tokens"]):
            df[t] = df.get(t, 0) + 1
    _CACHE = {"items": items, "avgdl": avgdl or 1.0, "df": df, "n": len(items)}
    return _CACHE


def _tf(tokens: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tokens:
        out[t] = out.get(t, 0) + 1
    return out


def _bm25(qtokens: list[str], it: dict, idx: dict, k1: float = 1.4, b: float = 0.75) -> float:
    score = 0.0
    n = idx["n"]
    for q in qtokens:
        if q not in it["tf"]:
            continue
        df = idx["df"].get(q, 0)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        f = it["tf"][q]
        score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * it["len"] / idx["avgdl"]))
    return score


def search(query: str, top_k: int = 4, min_score: float = 0.0) -> list[dict]:
    """混合检索。返回带 doc/chunk 定位的引用，供 AI 与页面共同使用。"""
    idx = _load()
    if not idx["items"] or not (query or "").strip():
        return []
    qt = tokenize(query)
    qv = embed(query)

    bm = sorted(
        ((i, _bm25(qt, i, idx)) for i in idx["items"]),
        key=lambda x: -x[1],
    )[:20]
    vec = sorted(((i, dot(qv, i["vec"])) for i in idx["items"]), key=lambda x: -x[1])[:20]

    rrf: dict[int, float] = {}
    picked: dict[int, dict] = {}
    for rank, (item, _s) in enumerate(bm):
        rrf[item["id"]] = rrf.get(item["id"], 0) + 1 / (60 + rank + 1)
        picked[item["id"]] = item
    for rank, (item, _s) in enumerate(vec):
        rrf[item["id"]] = rrf.get(item["id"], 0) + 1 / (60 + rank + 1)
        picked[item["id"]] = item

    ranked = sorted(rrf.items(), key=lambda x: -x[1])[:top_k]
    bm_score = {i["id"]: s for i, s in bm}
    out = []
    for cid, score in ranked:
        it = picked[cid]
        out.append(
            {
                "chunk_id": cid,
                "doc_id": it["doc_id"],
                "doc_title": it["title"],
                "section": f"第 {it['ord'] + 1} 段",
                "text": it["text"],
                "score": round(score, 5),
                "bm25": round(bm_score.get(cid, 0.0), 2),
                "ref": f"{it['title']}·第{it['ord'] + 1}段",
            }
        )
    return [o for o in out if o["score"] >= min_score]


def stats() -> dict:
    idx = _load()
    return {
        "docs": db.scalar("SELECT COUNT(*) FROM kb_docs"),
        "chunks": idx["n"],
        "avg_chunk_len": round(idx["avgdl"], 1) if idx["n"] else 0,
    }
