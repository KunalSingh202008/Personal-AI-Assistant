import hashlib
import logging
from pathlib import Path

from database import (
    delete_knowledge_document,
    get_all_chunks_with_embeddings,
    get_knowledge_chunks,
    get_knowledge_document,
    get_knowledge_document_by_path,
    list_knowledge_documents,
    save_knowledge_chunks,
    search_knowledge_chunks_fts,
    upsert_knowledge_document,
)
from .chunker import chunk_text
from .embeddings import cosine_similarity, generate_local_embedding
from .parser import parse_file

logger = logging.getLogger("nexus.knowledge")

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx",
    ".json", ".csv", ".pdf", ".html", ".htm", ".yaml", ".yml",
    ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls",
}

IGNORED_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", "dist", "build",
    ".idea", ".vscode",
}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def index_file(file_path: Path | str, source_id: int | None = None) -> dict:
    path = Path(file_path).resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")

    current_hash = _file_hash(path)
    file_path_str = str(path)

    existing = get_knowledge_document_by_path(file_path_str)
    if existing and existing["content_hash"] == current_hash and existing["status"] == "indexed":
        return {
            "status": "skipped",
            "reason": "unchanged",
            "document_id": existing["id"],
            "title": existing["title"],
            "chunk_count": existing["chunk_count"],
        }

    try:
        text, mime_type = parse_file(path)
    except Exception as exc:
        doc_id = upsert_knowledge_document(
            file_path=file_path_str,
            title=path.name,
            content_hash=current_hash,
            mime_type="unknown",
            size_bytes=path.stat().st_size,
            chunk_count=0,
            source_id=source_id,
            status="failed",
            error_message=str(exc),
        )
        return {
            "status": "failed",
            "document_id": doc_id,
            "title": path.name,
            "error": str(exc),
        }

    chunks = chunk_text(text)
    for chunk in chunks:
        chunk["embedding"] = generate_local_embedding(chunk["content"])

    doc_id = upsert_knowledge_document(
        file_path=file_path_str,
        title=path.name,
        content_hash=current_hash,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        chunk_count=len(chunks),
        source_id=source_id,
        status="indexed",
        error_message=None,
    )

    save_knowledge_chunks(doc_id, chunks)

    return {
        "status": "indexed",
        "document_id": doc_id,
        "title": path.name,
        "chunk_count": len(chunks),
        "mime_type": mime_type,
    }


def index_directory(
    dir_path: Path | str,
    source_id: int | None = None,
    recursive: bool = True,
) -> dict:
    directory = Path(dir_path).resolve()
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    indexed = 0
    skipped = 0
    failed = 0
    errors = []

    pattern = "**/*" if recursive else "*"
    for item in directory.glob(pattern):
        if any(part in IGNORED_DIRS for part in item.parts):
            continue
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                res = index_file(item, source_id=source_id)
                if res["status"] == "indexed":
                    indexed += 1
                elif res["status"] == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    errors.append(f"{item.name}: {res.get('error', 'unknown error')}")
            except Exception as exc:
                failed += 1
                errors.append(f"{item.name}: {str(exc)}")

    return {
        "directory": str(directory),
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:10],
    }


def search_knowledge_base(
    query: str,
    top_k: int = 5,
    hybrid: bool = True,
) -> list[dict]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    # 1. Lexical search using SQLite FTS5
    fts_results = search_knowledge_chunks_fts(cleaned_query, limit=top_k * 3)
    fts_map: dict[int, dict] = {}
    for rank, row in enumerate(fts_results, start=1):
        c_id = int(row["chunk_id"])
        fts_map[c_id] = {
            "chunk_id": c_id,
            "document_id": row["document_id"],
            "title": row["title"],
            "file_path": row["file_path"],
            "content": row["content"],
            "chunk_index": row["chunk_index"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "fts_rank": rank,
        }

    # 2. Semantic vector search
    query_vec = generate_local_embedding(cleaned_query)
    all_chunks = get_all_chunks_with_embeddings()
    vec_scores: list[tuple[float, dict]] = []

    for item in all_chunks:
        sim = cosine_similarity(query_vec, item["embedding"])
        if sim > 0.05:
            vec_scores.append((sim, item))

    vec_scores.sort(key=lambda x: x[0], reverse=True)
    vec_map: dict[int, tuple[int, float, dict]] = {}
    for rank, (score, item) in enumerate(vec_scores[: top_k * 3], start=1):
        c_id = item["chunk_id"]
        vec_map[c_id] = (rank, score, item)

    # 3. Hybrid Reciprocal Rank Fusion (RRF)
    all_chunk_ids = set(fts_map.keys()) | set(vec_map.keys())
    ranked_chunks = []

    k_rrf = 60.0
    for c_id in all_chunk_ids:
        score = 0.0
        meta = None

        if c_id in fts_map:
            fts_rank = fts_map[c_id]["fts_rank"]
            score += 1.0 / (k_rrf + fts_rank)
            meta = fts_map[c_id]

        if c_id in vec_map:
            vec_rank, vec_sim, vec_item = vec_map[c_id]
            score += 1.0 / (k_rrf + vec_rank)
            if meta is None:
                meta = {
                    "chunk_id": c_id,
                    "document_id": vec_item["document_id"],
                    "title": vec_item["title"],
                    "file_path": vec_item["file_path"],
                    "content": vec_item["content"],
                    "chunk_index": vec_item["chunk_index"],
                    "start_line": vec_item["start_line"],
                    "end_line": vec_item["end_line"],
                }

        if meta:
            ranked_chunks.append((score, meta))

    ranked_chunks.sort(key=lambda x: x[0], reverse=True)

    results = []
    for idx, (score, item) in enumerate(ranked_chunks[:top_k], start=1):
        content = item["content"]
        snippet = content[:300] + ("..." if len(content) > 300 else "")
        results.append({
            "citation_id": f"[{idx}]",
            "document_id": item["document_id"],
            "title": item["title"],
            "file_path": item["file_path"],
            "chunk_index": item["chunk_index"],
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
            "snippet": snippet,
            "content": content,
            "score": round(score, 4),
        })

    return results


def delete_indexed_document(doc_id: int) -> bool:
    return delete_knowledge_document(doc_id)


def list_indexed_documents() -> list[dict]:
    return list_knowledge_documents()


def get_document_details(doc_id: int) -> dict | None:
    doc = get_knowledge_document(doc_id)
    if not doc:
        return None
    chunks = get_knowledge_chunks(doc_id)
    doc["chunks"] = chunks
    return doc
