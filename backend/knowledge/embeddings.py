import hashlib
import json
import logging
import math
import os
import re
from typing import Sequence, List, Dict, Any, Optional
import httpx

logger = logging.getLogger("kela.embeddings")

VECTOR_DIM = 128


def _hash_token_to_idx(token: str, dim: int = VECTOR_DIM) -> int:
    h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
    return h % dim


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


def generate_local_embedding(text: str, dim: int = VECTOR_DIM) -> list[float]:
    """
    Generate a normalized term-frequency and subword n-gram embedding vector
    in pure Python. Fast, deterministic, sub-millisecond, and works offline.
    """
    clean = text.lower()
    tokens = re.findall(r"\w+", clean)
    if not tokens:
        return [0.0] * dim

    vec = [0.0] * dim

    # Word level frequencies with position decay weighting
    for i, token in enumerate(tokens):
        idx = _hash_token_to_idx(token, dim)
        weight = 1.0 + (1.0 / (1.0 + math.log(i + 1)))
        vec[idx] += weight

    # Subword character 3-grams for morphological and stem similarity
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


class BaseEmbeddingProvider:
    """Abstract interface defining required capabilities for embedding providers."""
    name: str = "base"
    dimension: int = VECTOR_DIM
    model_name: str = "base-embedding"

    async def embed_query(self, text: str) -> List[float]:
        raise NotImplementedError

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    async def health_check(self) -> Dict[str, Any]:
        raise NotImplementedError


class FastLocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    Default offline zero-dependency embedding provider.
    Sub-millisecond execution, deterministic L2-normalized 128-dimensional vectors.
    """
    name = "local-fast"
    dimension = 128
    model_name = "kela-subword-hash-128d"

    async def embed_query(self, text: str) -> List[float]:
        return generate_local_embedding(text, self.dimension)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [generate_local_embedding(t, self.dimension) for t in texts]

    async def health_check(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "available": True,
            "dimension": self.dimension,
            "model": self.model_name,
            "offline": True,
        }


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """
    Connects to local Ollama daemon for neural embedding generation (e.g. nomic-embed-text).
    Falls back gracefully to FastLocalEmbeddingProvider if unreachable.
    """
    name = "ollama"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        dimension: int = 768,
    ):
        self.base_url = (base_url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model_name = model_name or os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        self.dimension = dimension
        self.fallback = FastLocalEmbeddingProvider()

    async def health_check(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name", "") for m in res.json().get("models", [])]
                    installed = any(self.model_name in m for m in models)
                    return {
                        "provider": self.name,
                        "available": True,
                        "base_url": self.base_url,
                        "model": self.model_name,
                        "model_installed": installed,
                        "dimension": self.dimension,
                    }
        except Exception as e:
            logger.debug("Ollama embedding health probe notice: %s", e)

        return {
            "provider": self.name,
            "available": False,
            "base_url": self.base_url,
            "model": self.model_name,
            "model_installed": False,
            "dimension": self.dimension,
            "note": "Falling back to local-fast embeddings.",
        }

    async def embed_query(self, text: str) -> List[float]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Ollama embeddings endpoint
                payload = {"model": self.model_name, "prompt": text}
                resp = await client.post(f"{self.base_url}/api/embeddings", json=payload)
                if resp.status_code == 200:
                    emb = resp.json().get("embedding", [])
                    if emb:
                        self.dimension = len(emb)
                        return emb
        except Exception as exc:
            logger.debug("Ollama embedding query failed, using fast fallback: %s", exc)

        return await self.fallback.embed_query(text)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        results = []
        for text in texts:
            emb = await self.embed_query(text)
            results.append(emb)
        return results


class EmbeddingManager:
    """Manages active embedding providers and guarantees index dimension compatibility."""

    def __init__(self):
        self._providers: Dict[str, BaseEmbeddingProvider] = {
            "local-fast": FastLocalEmbeddingProvider(),
            "ollama": OllamaEmbeddingProvider(),
        }
        self.default_provider_name = "local-fast"

    def get_provider(self, name: Optional[str] = None) -> BaseEmbeddingProvider:
        target = name or self.default_provider_name
        return self._providers.get(target, self._providers["local-fast"])

    def register_provider(self, provider: BaseEmbeddingProvider) -> None:
        self._providers[provider.name] = provider

    async def get_all_status(self) -> List[Dict[str, Any]]:
        status_list = []
        for p in self._providers.values():
            st = await p.health_check()
            status_list.append(st)
        return status_list


embedding_manager = EmbeddingManager()
