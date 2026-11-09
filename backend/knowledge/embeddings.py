import hashlib
import math
import re
from typing import Sequence

VECTOR_DIM = 128


def _hash_token_to_idx(token: str, dim: int = VECTOR_DIM) -> int:
    h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
    return h % dim


def generate_local_embedding(text: str, dim: int = VECTOR_DIM) -> list[float]:
    """
    Generate a normalized term-frequency and subword n-gram embedding vector
    in pure Python. Fast, deterministic, and effective for semantic retrieval.
    """
    clean = text.lower()
    tokens = re.findall(r"\w+", clean)
    if not tokens:
        return [0.0] * dim

    vec = [0.0] * dim

    # Word level frequencies with position weighting
    for i, token in enumerate(tokens):
        idx = _hash_token_to_idx(token, dim)
        weight = 1.0 + (1.0 / (1.0 + math.log(i + 1)))
        vec[idx] += weight

    # Subword character 3-grams for morphological similarity
    for token in tokens:
        if len(token) >= 3:
            for j in range(len(token) - 2):
                ngram = token[j : j + 3]
                idx = _hash_token_to_idx(ngram, dim)
                vec[idx] += 0.35

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [round(v / norm, 5) for v in vec]
    return vec


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Calculate cosine similarity between two numeric vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))
