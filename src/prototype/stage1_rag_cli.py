#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 1 最小原型：制度问答 CLI（RAG：FAISS 向量 + BM25 混合检索 + LLM 生成）

用法：
    # 1) 制度文档入库（切片 → 向量化 → 存 FAISS）
    python stage1_rag_cli.py ingest data/客房管理制度示例.md

    # 2) 单问模式
    python stage1_rag_cli.py ask "退房后多久可以标记为可售？"

    # 3) 交互模式（不传问题即进入 REPL，输入 q 退出）
    python stage1_rag_cli.py

配置（环境变量，均可选，未配置时走离线兜底）：
    LLM_BASE_URL   OpenAI 兼容地址，如 https://api.deepseek.com/v1
    LLM_API_KEY    供应商密钥
    LLM_MODEL      对话模型名
    EMBED_BASE_URL / EMBED_API_KEY / EMBED_MODEL   向量接口（缺省复用 LLM_* 配置）

依赖：pip install faiss-cpu numpy httpx
"""

import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np

# =====================================================================
# 【核心模块 0 · 全阶段复用】配置管理
# ---------------------------------------------------------------------
# 阶段 2 会迁入 app/core/config.py（pydantic-settings）。
# 设计要点：所有供应商信息只在这里出现，业务代码只读 Settings 实例，
# 换供应商 = 改环境变量，不改代码。
# =====================================================================
class Settings:
    """集中读取环境变量；未配置的项给离线兜底值"""

    def __init__(self):
        # LLM（对话）供应商：OpenAI 兼容协议
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat")
        # 向量供应商：缺省复用 LLM 配置（多数供应商两者同源）
        self.embed_base_url = os.getenv("EMBED_BASE_URL", self.llm_base_url).rstrip("/")
        self.embed_api_key = os.getenv("EMBED_API_KEY", self.llm_api_key)
        self.embed_model = os.getenv("EMBED_MODEL", "text-embedding-v3")
        # 是否具备真实 LLM 调用条件
        self.llm_ready = bool(self.llm_base_url and self.llm_api_key)

        # RAG 参数（阶段 2 迁入配置文件）
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "500"))   # 切片目标长度（字）
        self.top_k = int(os.getenv("TOP_K", "3"))               # 混合检索取 top3
        self.index_dir = Path(os.getenv("INDEX_DIR", "rag_index"))


SETTINGS = Settings()

# =====================================================================
# 【核心模块 1 · 全阶段复用】LLM 调用封装（供应商可配置）
# ---------------------------------------------------------------------
# 阶段 2 迁入 app/agents/llm/{provider,openai_like,factory}.py。
# 设计要点：
#   a) 对外只暴露一个 chat() 函数签名，业务层不感知供应商；
#   b) 用 httpx 直连 OpenAI 兼容端点（/chat/completions），不锁死任何 SDK；
#   c) 异常向上抛，由调用方决定降级策略（本原型的降级 = 输出检索摘要）。
# =====================================================================
def chat_llm(prompt: str, system: str = "") -> str:
    """
    调用 OpenAI 兼容 LLM 生成回答。

    :param prompt:  用户问题（已拼入检索到的制度条款上下文）
    :param system: 系统提示词（约束模型"只依据条款回答"）
    :return: 模型生成的回答文本
    :raises RuntimeError: 未配置供应商或接口调用失败
    """
    if not SETTINGS.llm_ready:
        raise RuntimeError("未配置 LLM_BASE_URL / LLM_API_KEY，无法调用真实 LLM")

    import httpx  # 延迟导入：离线模式下不强制安装

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # —— OpenAI 兼容协议的标准请求体，换供应商只需改 base_url/model ——
    resp = httpx.post(
        f"{SETTINGS.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {SETTINGS.llm_api_key}"},
        json={"model": SETTINGS.llm_model, "messages": messages, "temperature": 0.2},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# =====================================================================
# 【核心模块 2 · 全阶段复用】Embedding 封装（API 优先，本地哈希兜底）
# ---------------------------------------------------------------------
# 阶段 2 迁入 app/rag/embedder.py，兜底实现删除（届时必须接真实向量接口）。
# 设计要点：
#   a) API 路径走 OpenAI 兼容 /embeddings 端点；
#   b) 离线兜底 = 字符 n-gram 哈希向量：保证"没有密钥也能跑通全链路"，
#      用于演示检索流程，检索质量有限（会在结果里明确标注）。
# =====================================================================
def embed_texts(texts: list[str]) -> np.ndarray:
    """
    批量向量化。

    :param texts: 文本列表（制度切片 或 查询）
    :return: 形状 (len(texts), dim) 的 float32 矩阵
    """
    if SETTINGS.embed_base_url and SETTINGS.embed_api_key:
        return _embed_via_api(texts)
    return _embed_local_fallback(texts)


def _embed_via_api(texts: list[str]) -> np.ndarray:
    """走 OpenAI 兼容 /embeddings 端点（阶段 2 的正式路径）"""
    import httpx

    out = []
    for t in texts:  # 逐条请求：简单可靠；阶段 2 改批量接口
        resp = httpx.post(
            f"{SETTINGS.embed_base_url}/embeddings",
            headers={"Authorization": f"Bearer {SETTINGS.embed_api_key}"},
            json={"model": SETTINGS.embed_model, "input": t},
            timeout=30,
        )
        resp.raise_for_status()
        out.append(resp.json()["data"][0]["embedding"])
    return np.asarray(out, dtype=np.float32)


def _embed_local_fallback(texts: list[str], dim: int = 256) -> np.ndarray:
    """
    离线兜底向量：字符 2-gram → 哈希桶累加 → L2 归一化。
    无语义能力，但保证脚本零配置可运行；结果中会标注"离线兜底向量"。

    注意：必须用稳定的哈希算法（md5），不能用内置 hash()——
    内置 hash 随进程随机化，会导致同一文档每次入库的向量不同、
    检索结果不可复现（阶段 2 接真实 embedding 接口后此函数删除）。
    """
    import hashlib

    mat = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        for j in range(len(t) - 1):
            gram = t[j : j + 2]
            bucket = int.from_bytes(hashlib.md5(gram.encode("utf-8")).digest()[:4], "big")
            mat[i, bucket % dim] += 1.0  # 确定性落桶
    norm = np.linalg.norm(mat, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return mat / norm


# =====================================================================
# 【核心模块 3 · 全阶段复用】制度文档切片器
# ---------------------------------------------------------------------
# 阶段 2 迁入 app/rag/splitter.py。
# 设计要点：
#   a) 优先按「第X条」条款边界切——引用时能落到条款号（架构文档 4.4）；
#   b) 无条款结构时按 500 字硬切；
#   c) 切片是确定性纯函数（同样输入永远同样输出），方便单测。
# =====================================================================
def split_policy(doc_text: str, chunk_size: int = None) -> list[dict]:
    """
    :param doc_text:  制度文档全文
    :param chunk_size: 目标切片长度（字），默认取 SETTINGS.chunk_size
    :return: [{"clause_no": "第十二条", "content": "...", "seq": 0}, ...]
    """
    chunk_size = chunk_size or SETTINGS.chunk_size

    # —— 步骤 1：按「第X条」把全文切成 (条款号, 条款文本) 序列 ——
    pattern = re.compile(r"^(第[一二三四五六七八九十百\d]+条)[、.\s]*(.*)$", re.M)
    matches = list(pattern.finditer(doc_text))
    sections: list[tuple[str, str]] = []

    if matches:  # 文档有条款结构
        for idx, m in enumerate(matches):
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(doc_text)
            body = doc_text[start:end].strip()
            sections.append((m.group(1), body))
    else:  # 无条款结构：整篇当一块，走硬切
        sections.append(("", doc_text.strip()))

    # —— 步骤 2：剔除章节标题行（「# …」），避免混入切片正文 ——
    cleaned = [
        (no, "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#")).strip())
        for no, body in sections
    ]
    cleaned = [(no, body) for no, body in cleaned if body]

    # —— 步骤 3：超过 chunk_size 的条款继续细切（在句号处优先断开）——
    chunks: list[dict] = []
    for clause_no, body in cleaned:
        if len(body) <= chunk_size:
            chunks.append({"clause_no": clause_no, "content": body})
            continue
        # 按句切，尽量不打断句子
        buf, buf_len = "", 0
        for sent in re.split(r"(?<=[。；\n])", body):
            if buf_len + len(sent) > chunk_size and buf:
                chunks.append({"clause_no": clause_no, "content": buf.strip()})
                buf, buf_len = "", 0
            buf += sent
            buf_len += len(sent)
        if buf.strip():
            chunks.append({"clause_no": clause_no, "content": buf.strip()})

    # —— 步骤 4：编号并返回 ——
    for i, c in enumerate(chunks):
        c["seq"] = i
    return chunks


# =====================================================================
# 【核心模块 4 · 全阶段复用】中文分词（BM25 用）
# ---------------------------------------------------------------------
# 阶段 2 迁入 app/rag/retriever.py 内部。
# 优先 jieba（效果更好），未安装则退化为字符 bigram（零依赖可跑）。
# =====================================================================
def tokenize(text: str) -> list[str]:
    try:
        import jieba  # type: ignore

        return [w for w in jieba.lcut(text) if w.strip()]
    except ImportError:
        return [text[i : i + 2] for i in range(len(text) - 1)] or [text]


# =====================================================================
# 【核心模块 5 · 全阶段复用】BM25 索引（纯 Python 实现）
# ---------------------------------------------------------------------
# 阶段 2 若引入 rank_bm25/elasticsearch 可整体替换，接口不变。
# 公式：标准 BM25（k1=1.5, b=0.75），细节注释见函数内。
# =====================================================================
class BM25Index:
    def __init__(self, docs_tokens: list[list[str]]):
        self.k1, self.b = 1.5, 0.75
        self.doc_count = len(docs_tokens)
        self.doc_lens = [len(t) for t in docs_tokens]
        self.avgdl = sum(self.doc_lens) / max(self.doc_count, 1)
        # df：包含某词的文档数（算 IDF 用）
        df: dict[str, int] = {}
        for tokens in docs_tokens:
            for w in set(tokens):
                df[w] = df.get(w, 0) + 1
        self.idf = {
            w: math.log((self.doc_count - n + 0.5) / (n + 0.5) + 1)
            for w, n in df.items()
        }
        self.doc_freqs = [self._count(tokens) for tokens in docs_tokens]

    @staticmethod
    def _count(tokens: list[str]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for w in tokens:
            freq[w] = freq.get(w, 0) + 1
        return freq

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """返回 [(doc_idx, bm25得分)]，按得分降序取前 top_k"""
        scores = []
        q_tokens = tokenize(query)
        for i, freqs in enumerate(self.doc_freqs):
            s = 0.0
            for w in q_tokens:
                if w not in freqs:
                    continue
                idf = self.idf.get(w, 0.0)
                tf = freqs[w]
                # BM25 词项得分：TF 饱和 + 文档长度归一
                s += idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * self.doc_lens[i] / self.avgdl)
                )
            scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# =====================================================================
# 【核心模块 6 · 全阶段复用】混合检索器（FAISS 向量 + BM25，RRF 融合）
# ---------------------------------------------------------------------
# 阶段 2 迁入 app/rag/retriever.py，FAISS 替换为 pgvector（架构已定）。
# 融合策略：RRF（Reciprocal Rank Fusion）——只用排名不用原始分数，
# 两种检索分数量纲不同也能稳健融合：score = Σ 1/(60 + rank)。
# =====================================================================
class HybridRetriever:
    def __init__(self, chunks: list[dict], embeddings: np.ndarray):
        import faiss  # 延迟导入：仅 ingest/ask 时需要

        self.chunks = chunks
        self.embeddings = embeddings.astype(np.float32)
        dim = self.embeddings.shape[1]
        # IndexFlatIP + 归一化向量 = 余弦相似度（小规模精确检索，够用）
        faiss.normalize_L2(self.embeddings)
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_index.add(self.embeddings)
        # BM25 建在切片全文上
        self.bm25 = BM25Index([tokenize(c["content"]) for c in chunks])

    def search(self, query: str, top_k: int = None) -> list[dict]:
        """
        混合检索入口（阶段 2 的 agent 工具层直接调这个方法）。

        :param query: 用户原始问题
        :param top_k: 返回条数，默认 SETTINGS.top_k
        :return: [{"clause_no","content","score","rank"}]，按 RRF 分数降序
        """
        import faiss

        top_k = top_k or SETTINGS.top_k
        candidate_k = max(top_k * 5, 10)  # 两路各取较大候选集再融合

        # —— 路 1：向量检索（语义泛化，问法不同也能召回）——
        q_vec = embed_texts([query]).astype(np.float32)
        faiss.normalize_L2(q_vec)
        _, vec_ids = self.faiss_index.search(q_vec, candidate_k)
        vec_ranking = [int(i) for i in vec_ids[0] if 0 <= i < len(self.chunks)]

        # —— 路 2：BM25 检索（关键词精确命中，如条款号/专有名词）——
        bm25_ranking = [i for i, _ in self.bm25.search(query, candidate_k)]

        # —— RRF 融合：两路排名合成一个分数 ——
        rrf: dict[int, float] = {}
        for rank, i in enumerate(vec_ranking):
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank + 1)
        for rank, i in enumerate(bm25_ranking):
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank + 1)

        merged = sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for rank, (i, score) in enumerate(merged):
            c = dict(self.chunks[i])
            c["score"] = round(score, 5)
            c["rank"] = rank
            results.append(c)
        return results


# =====================================================================
# 【主流程 1】ingest：制度文档 → 切片 → 向量化 → 持久化 FAISS 索引
# ---------------------------------------------------------------------
# 阶段 2 对应 scripts/ingest_docs.py（入库到 pgvector + policy_chunks 表）。
# 本原型持久化到本地文件：rag_index/{chunks.json, vectors.npy}
# =====================================================================
def ingest(md_path: str) -> int:
    doc_path = Path(md_path)
    if not doc_path.exists():
        print(f"[错误] 文件不存在：{doc_path}")
        return 1

    doc_text = doc_path.read_text(encoding="utf-8")
    chunks = split_policy(doc_text)
    if not chunks:
        print("[错误] 未切出任何内容，请检查文档格式")
        return 1

    print(f"[切片] {doc_path.name} → {len(chunks)} 块（目标 {SETTINGS.chunk_size} 字/块）")
    for c in chunks[:3]:
        print(f"    · {c['clause_no'] or '(无条款号)'} seq={c['seq']} 长度={len(c['content'])}")
    if len(chunks) > 3:
        print(f"    · ... 共 {len(chunks)} 块")

    vecs = embed_texts([c["content"] for c in chunks])
    mode = "API 向量" if (SETTINGS.embed_base_url and SETTINGS.embed_api_key) else "离线兜底向量"
    print(f"[向量化] {len(chunks)} 块 × {vecs.shape[1]} 维（{mode}）")

    SETTINGS.index_dir.mkdir(parents=True, exist_ok=True)
    np.save(SETTINGS.index_dir / "vectors.npy", vecs)
    (SETTINGS.index_dir / "chunks.json").write_text(
        json.dumps(
            {"source": str(doc_path), "chunk_count": len(chunks), "chunks": chunks},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[完成] 索引已保存到 {SETTINGS.index_dir}/")
    return 0


# =====================================================================
# 【主流程 2】ask：加载索引 → 混合检索 top3 → 拼 Prompt → LLM 生成
# ---------------------------------------------------------------------
# 阶段 2 对应 app/agents/orchestrator.py 的 POLICY_QA 分支：
#   检索结果拼上下文 → system 约束"只依据条款" → 调 chat_llm → 返回带引用回答。
# =====================================================================
def _load_retriever() -> HybridRetriever | None:
    chunks_file = SETTINGS.index_dir / "chunks.json"
    vec_file = SETTINGS.index_dir / "vectors.npy"
    if not (chunks_file.exists() and vec_file.exists()):
        print(f"[错误] 索引不存在（{SETTINGS.index_dir}/），请先执行 ingest")
        return None
    data = json.loads(chunks_file.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    vecs = np.load(vec_file)
    return HybridRetriever(chunks, vecs)


def build_prompt(question: str, hits: list[dict]) -> str:
    """
    把检索命中的制度条款拼进用户问题。
    【阶段 2 复用】这是 POLICY_QA 分支的提示词模板，护栏要求写死：
    只依据条款回答 + 必须引用条款号 + 无依据要明说。
    """
    context = "\n\n".join(
        f"【{h['clause_no'] or f'片段{h['rank'] + 1}'}】{h['content']}" for h in hits
    )
    return (
        f"你是酒店管理制度的问答助手。请只依据下面的制度条款回答问题，"
        f"并在回答中注明所引用的条款号；如果条款中没有依据，"
        f"请明确回答\"当前制度库中未找到依据\"，不要编造。\n\n"
        f"=== 制度条款 ===\n{context}\n\n=== 问题 ===\n{question}"
    )


SYSTEM_PROMPT = (
    "你是山海旅居的制度问答助手。回答必须：1) 只基于提供的制度条款；"
    "2) 引用条款号作为出处；3) 无依据时明说未找到；4) 不出现房号、工号、手机号。"
)


def ask(question: str) -> None:
    retriever = _load_retriever()
    if retriever is None:
        return

    # —— 混合检索 top3（【核心模块 6】阶段 2 直接复用的调用形态）——
    hits = retriever.search(question)
    print(f"\n=== 检索结果 top{len(hits)} ===")
    for h in hits:
        preview = h["content"][:60].replace("\n", " ")
        print(f"  #{h['rank'] + 1} [{h['clause_no'] or '无条款号'}] rrf={h['score']} {preview}…")

    if not hits:
        print("\n未检索到相关条款，请先 ingest 制度文档。")
        return

    prompt = build_prompt(question, hits)

    # —— 调 LLM 生成（【核心模块 1】）；未配置密钥则降级输出检索摘要 ——
    if SETTINGS.llm_ready:
        try:
            answer = chat_llm(prompt, system=SYSTEM_PROMPT)
            print(f"\n=== 回答（{SETTINGS.llm_model}）===\n{answer}")
        except Exception as e:  # 网络/鉴权失败也走降级，保证 CLI 不崩
            print(f"\n[LLM 调用失败] {e}")
            _fallback_answer(question, hits)
    else:
        print("\n[未配置 LLM_API_KEY，以下为检索摘要（未调用大模型）]")
        _fallback_answer(question, hits)


def _fallback_answer(question: str, hits: list[dict]) -> None:
    """降级输出：把 top3 条款原文给用户，人肉阅读也算可用 :)"""
    for h in hits:
        print(f"\n--- {h['clause_no'] or f'片段{h['rank'] + 1}'} ---\n{h['content']}")


# =====================================================================
# CLI 入口
# =====================================================================
def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "ingest":
        sys.exit(ingest(args[1] if len(args) > 1 else "data/客房管理制度示例.md"))
    if args and args[0] == "ask":
        ask(" ".join(args[1:]))
        return
    if args:  # 直接把整个参数当问题（python xx.py 问题）
        ask(" ".join(args))
        return

    # 交互模式
    print("制度问答原型（输入问题回车作答，q 退出）。当前索引目录：", SETTINGS.index_dir)
    if not SETTINGS.llm_ready:
        print("提示：未配置 LLM_API_KEY，将以检索摘要模式运行。")
    while True:
        try:
            q = input("\n问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q or q.lower() in ("q", "quit", "exit"):
            break
        ask(q)


if __name__ == "__main__":
    main()
