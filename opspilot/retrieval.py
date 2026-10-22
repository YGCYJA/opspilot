"""BM25 + character TF-IDF RRF; optional local neural embeddings.

The default hybrid is deliberately labelled lexical, not semantic retrieval.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    title: str
    text: str
    line_start: int
    line_end: int


def tokenize(text: str) -> list[str]:
    terms = re.findall(r"[a-z0-9_]+(?:-[a-z0-9_]+)*|[\u4e00-\u9fff]+", text.lower())
    return [token for term in terms for token in
            ([term] if not re.fullmatch(r"[\u4e00-\u9fff]+", term) or len(term) < 2
             else [term[i:i + 2] for i in range(len(term) - 1)])]


def chargrams(text: str) -> list[str]:
    value = re.sub(r"\s+", "", text.lower())
    return [value[i:i + 3] for i in range(max(0, len(value) - 2))]


def ingest(directory: Path, max_chars: int = 480, overlap_lines: int = 1) -> list[Chunk]:
    """Split at Markdown headings and bounded line windows; retain source lines.

    Long single lines are split into bounded spans sharing the source line.
    Chunk IDs include source position and content, so stale citations change IDs.
    """
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    if type(overlap_lines) is not int or overlap_lines < 0:
        raise ValueError("overlap_lines must be a non-negative integer")
    chunks = []
    for path in sorted(directory.rglob("*.md")):
        if path.is_symlink():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        title = path.stem
        section: list[tuple[int, str]] = []

        def emit(items: list[tuple[int, str]], heading: str) -> None:
            pending: list[tuple[int, str]] = []
            for number, line in items:
                for offset in range(0, len(line), max_chars):
                    part = line[offset:offset + max_chars]
                    if pending and len("\n".join(s for _, s in pending)) + len(part) + 1 > max_chars:
                        append(pending, heading)
                        pending = pending[-overlap_lines:] if overlap_lines else []
                        if sum(len(s) + 1 for _, s in pending) + len(part) > max_chars:
                            pending = []
                    pending.append((number, part))
            if pending:
                append(pending, heading)

        def append(items: list[tuple[int, str]], heading: str) -> None:
            body = "\n".join(line for _, line in items).strip()
            if not body:
                return
            doc_id = path.relative_to(directory).as_posix()
            digest = hashlib.sha256(f"{doc_id}:{items[0][0]}:{body}".encode()).hexdigest()[:14]
            chunks.append(Chunk(digest, doc_id, heading, body, items[0][0], items[-1][0]))

        for number, line in enumerate(lines, 1):
            if line.startswith("#"):
                emit(section, title)
                section = []
                title = line.lstrip("# ").strip()
            elif line.strip():
                section.append((number, line))
        emit(section, title)
    return chunks


def save_index(chunks: list[Chunk], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=2), encoding="utf-8")


class Retriever:
    def __init__(self, chunks: list[Chunk], embedding_model: str | None = None, query_prefix: str = ""):
        self.chunks = chunks
        self.terms = [Counter(tokenize(c.title + " " + c.text)) for c in chunks]
        self.lengths = [sum(t.values()) for t in self.terms]
        self.average_length = sum(self.lengths) / max(1, len(chunks))
        df = Counter(t for document in self.terms for t in document)
        self.idf = {t: math.log(1 + (len(chunks) - n + .5) / (n + .5)) for t, n in df.items()}
        grams = [Counter(chargrams(c.title + " " + c.text)) for c in chunks]
        gram_df = Counter(g for document in grams for g in document)
        self.gram_idf = {g: math.log((1 + len(chunks)) / (1 + n)) + 1 for g, n in gram_df.items()}
        self.vectors = [self._vector(g) for g in grams]
        self.encoder = None
        self.dense = None
        self.query_prefix = query_prefix
        if embedding_model:
            from sentence_transformers import SentenceTransformer
            # A path is required: no silent model download during startup.
            if not Path(embedding_model).is_dir():
                raise ValueError("OPS_EMBED_MODEL must point to an existing local model directory")
            self.encoder = SentenceTransformer(embedding_model, local_files_only=True, device="cpu")
            self.dense = self.encoder.encode([c.title + "\n" + c.text for c in chunks], normalize_embeddings=True, show_progress_bar=False)

    def _vector(self, counts: Counter) -> dict[str, float]:
        raw = {g: (1 + math.log(n)) * self.gram_idf[g] for g, n in counts.items() if g in self.gram_idf}
        norm = math.sqrt(sum(v * v for v in raw.values())) or 1
        return {g: v / norm for g, v in raw.items()}

    def search(self, query: str, k: int = 5, method: str = "hybrid") -> list[dict]:
        if type(k) is not int or k < 1:
            raise ValueError("k must be a positive integer")
        if method not in {"bm25", "tfidf", "hybrid", "semantic"}:
            raise ValueError("Unknown retrieval method")
        tokens = Counter(tokenize(query))
        if not tokens or not self.chunks:
            return []
        bm25 = []
        for document, length in zip(self.terms, self.lengths):
            score = sum(self.idf.get(t, 0) * document[t] * 2.5 /
                        (document[t] + 1.5 * (.25 + .75 * length / self.average_length))
                        for t in tokens if document[t])
            bm25.append(score)
        qv = self._vector(Counter(chargrams(query)))
        cosine = [sum(v * dv.get(g, 0) for g, v in qv.items()) for dv in self.vectors]
        if method == "semantic":
            if self.encoder is None:
                raise ValueError("Semantic retrieval requires OPS_EMBED_MODEL")
            vector = self.encoder.encode([self.query_prefix + query], normalize_embeddings=True, show_progress_bar=False)[0]
            secondary = (self.dense @ vector).tolist()
        else:
            secondary = cosine

        def ranked(scores):
            return sorted((i for i, v in enumerate(scores) if v > 0), key=lambda i: (-scores[i], self.chunks[i].id))

        if method in {"hybrid", "semantic"}:
            fused = [0.0] * len(self.chunks)
            for scores in (bm25, secondary):
                for rank, i in enumerate(ranked(scores), 1):
                    fused[i] += 1 / (60 + rank)
            scores = fused
        else:
            scores = bm25 if method == "bm25" else cosine
        result = []
        for i in ranked(scores)[:k]:
            coverage = len(set(tokens) & set(self.terms[i])) / max(1, len(tokens))
            result.append({**asdict(self.chunks[i]), "score": round(scores[i], 6),
                           "bm25": round(bm25[i], 4), "coverage": round(coverage, 4),
                           "cosine": round(cosine[i], 4), "method": method})
        return result
