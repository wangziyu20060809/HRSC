# -*- coding: utf-8 -*-
"""kb/embedder.py — 中文分词与轻量向量化

MVP 选型：
- 分词不引 jieba（省一个依赖、避免词典与酒店术语不匹配），用「中文二元组 + 英文数字词 + 单字兜底」；
  对「已清扫 / 可售 / 查房」这类短术语，二元组检索效果足够，且完全确定性可回归。
- 向量用 md5 哈希到 256 维（signed hashing），归一化后余弦等价点积。
  好处：零外部调用、离线可跑、重建索引毫秒级；
  代价：没有语义泛化能力，同义改写要靠 KB 文档自己写全（已在文档里做了同义词展开）。
  生产替换点：把 embed() 换成 text-embedding-v3 或 bge-m3，接口不变。
"""

from __future__ import annotations

import hashlib
import math
import re
import struct

DIM = 256

_ASCII = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = _ASCII.findall(text)
    for seg in _CJK.findall(text):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
            tokens.append(seg)  # 整段也作为特征，保留短语级线索
    return tokens


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    counts: dict[str, int] = {}
    for t in tokenize(text):
        counts[t] = counts.get(t, 0) + 1
    for tok, cnt in counts.items():
        h = hashlib.md5(tok.encode("utf-8")).digest()
        idx = struct.unpack("<I", h[:4])[0] % DIM
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log(cnt))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{DIM}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{DIM}f", blob))


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
