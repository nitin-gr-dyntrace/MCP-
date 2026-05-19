"""
Semantic search using sentence-transformers embeddings.
Falls back to TF-IDF cosine similarity if the model is unavailable.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CorpusEntry

# ---------------------------------------------------------------------------
# Model loading — optional, graceful fallback
# ---------------------------------------------------------------------------
try:
    import os
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from sentence_transformers import SentenceTransformer
    import numpy as np

    _MODEL: SentenceTransformer | None = SentenceTransformer("all-MiniLM-L6-v2")
    EMBEDDINGS_AVAILABLE = True
except Exception:
    _MODEL = None
    EMBEDDINGS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Embedding cache — stored alongside the corpus
# ---------------------------------------------------------------------------
def _embedding_cache_path(corpus_path: Path) -> Path:
    return corpus_path.parent / "embeddings_cache.json"


def _load_embedding_cache(corpus_path: Path) -> dict[str, list[float]]:
    path = _embedding_cache_path(corpus_path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_embedding_cache(corpus_path: Path, cache: dict[str, list[float]]) -> None:
    try:
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        _embedding_cache_path(corpus_path).write_text(
            json.dumps(cache), encoding="utf-8"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core embedding helpers
# ---------------------------------------------------------------------------
def _embed(text: str) -> list[float] | None:
    if not EMBEDDINGS_AVAILABLE or _MODEL is None:
        return None
    try:
        import numpy as np
        vec = _MODEL.encode(text, convert_to_numpy=True)
        return vec.tolist()
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    import numpy as np
    va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def embed_query(query: str) -> list[float] | None:
    """Return the embedding for a query string, or None if unavailable."""
    return _embed(query)


def embedding_score(
    entry: "CorpusEntry",
    query_vec: list[float] | None,
    corpus_path: Path,
) -> float:
    """
    Return cosine similarity between query and corpus entry.
    Uses the on-disk embedding cache; generates and caches on first call.
    Returns 0.0 if embeddings are unavailable.
    """
    if query_vec is None or not EMBEDDINGS_AVAILABLE:
        return 0.0

    cache = _load_embedding_cache(corpus_path)
    key = entry.url

    if key not in cache:
        text = f"{entry.title} {entry.excerpt}"
        vec = _embed(text)
        if vec is None:
            return 0.0
        cache[key] = vec
        _save_embedding_cache(corpus_path, cache)

    return _cosine(query_vec, cache[key])


def rerank_with_embeddings(
    entries: list["CorpusEntry"],
    query: str,
    corpus_path: Path,
    tfidf_scores: dict[str, float],
    top_k: int = 10,
    alpha: float = 0.60,
) -> list[tuple["CorpusEntry", float]]:
    """
    Hybrid rerank: alpha * embedding_score + (1-alpha) * tfidf_score.

    alpha=0.60 means embeddings dominate; lower it to trust TF-IDF more.
    Falls back to pure TF-IDF if embeddings are unavailable.
    """
    query_vec = embed_query(query) if EMBEDDINGS_AVAILABLE else None

    scored: list[tuple["CorpusEntry", float]] = []
    for entry in entries:
        tfidf = tfidf_scores.get(entry.url, 0.0)
        if query_vec is not None:
            emb = embedding_score(entry, query_vec, corpus_path)
            score = alpha * emb + (1.0 - alpha) * tfidf
        else:
            score = tfidf
        scored.append((entry, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
