"""轻量记忆检索模型：从 memory 文本中返回最相关的 3-5 条。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from memory import get_project_memory_dir

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]+")


@dataclass
class MemoryHit:
    """单条记忆命中结果。"""

    score: float
    text: str
    source_file: str


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _split_memory_text(text: str) -> List[str]:
    """把 markdown 文本切成候选段落。"""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    chunks: List[str] = []
    buff: List[str] = []

    def _flush() -> None:
        if not buff:
            return
        segment = " ".join(x for x in buff if x)
        if segment:
            chunks.append(segment)
        buff.clear()

    for line in lines:
        if not line:
            _flush()
            continue
        if line.startswith("#"):
            _flush()
            continue
        if line.startswith(("-", "*", "+", "1.", "2.", "3.", "4.", "5.")):
            _flush()
            cleaned = line.lstrip("-*+0123456789. ").strip()
            if cleaned:
                chunks.append(cleaned)
            continue
        buff.append(line)

    _flush()
    return chunks


def _collect_memory_chunks(memory_root: Path) -> List[Dict[str, str]]:
    chunks: List[Dict[str, str]] = []
    if not memory_root.exists():
        return chunks

    for file_path in sorted(memory_root.rglob("*.md")):
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            continue

        for seg in _split_memory_text(content):
            if len(seg) < 6:
                continue
            chunks.append({
                "text": seg,
                "source_file": str(file_path),
            })
    return chunks


class MemoryRetriever:
    """基于 TF-IDF 风格打分的轻量检索器。"""

    def __init__(self, chunks: Sequence[Dict[str, str]]) -> None:
        self.chunks = list(chunks)
        self._doc_tokens: List[List[str]] = [_tokenize(c["text"]) for c in self.chunks]
        self._idf: Dict[str, float] = self._build_idf(self._doc_tokens)

    @staticmethod
    def _build_idf(doc_tokens: Sequence[Sequence[str]]) -> Dict[str, float]:
        df: Dict[str, int] = {}
        n = max(1, len(doc_tokens))
        for toks in doc_tokens:
            for tk in set(toks):
                df[tk] = df.get(tk, 0) + 1
        return {tk: math.log((n + 1) / (cnt + 1)) + 1.0 for tk, cnt in df.items()}

    def retrieve(self, query: str, top_k: int = 5) -> List[MemoryHit]:
        q_tokens = _tokenize(query)
        if not q_tokens or not self.chunks:
            return []

        k = max(3, min(5, int(top_k)))
        hits: List[MemoryHit] = []

        for idx, doc in enumerate(self.chunks):
            d_tokens = self._doc_tokens[idx]
            if not d_tokens:
                continue

            tf: Dict[str, int] = {}
            for tk in d_tokens:
                tf[tk] = tf.get(tk, 0) + 1

            score = 0.0
            for q in q_tokens:
                if q not in tf:
                    continue
                score += (tf[q] / len(d_tokens)) * self._idf.get(q, 0.0)

            if score <= 0:
                continue

            hits.append(
                MemoryHit(
                    score=score,
                    text=doc["text"],
                    source_file=doc["source_file"],
                )
            )

        hits.sort(key=lambda x: x.score, reverse=True)
        return hits[:k]


def retrieve_memories(question: str, top_k: int = 5, cwd: Path | None = None) -> List[MemoryHit]:
    """从项目 memory 目录检索与问题最相关的 3-5 条记忆。"""
    root = get_project_memory_dir(cwd)
    chunks = _collect_memory_chunks(root)
    retriever = MemoryRetriever(chunks)
    return retriever.retrieve(question, top_k=top_k)
