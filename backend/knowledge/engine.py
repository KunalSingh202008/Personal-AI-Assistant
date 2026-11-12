import asyncio
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

from database import (
    create_knowledge_base as db_create_kb,
    delete_knowledge_base as db_delete_kb,
    delete_knowledge_document,
    get_all_chunks_with_embeddings,
    get_knowledge_base,
    get_knowledge_chunks,
    get_knowledge_document,
    get_knowledge_document_by_path,
    get_knowledge_document_by_hash,
    list_knowledge_bases as db_list_kbs,
    list_knowledge_documents,
    save_knowledge_chunks,
    search_knowledge_chunks_fts,
    upsert_knowledge_document,
)
from .chunker import chunk_text, chunk_sections
from .embeddings import (
    cosine_similarity,
    generate_local_embedding,
    embedding_manager,
)
from .parser import (
    parse_document_sections,
    parse_file,
    sanitize_filename,
    validate_file_safety,
    SUPPORTED_EXTENSIONS,
)

logger = logging.getLogger("kela.knowledge.engine")

KNOWLEDGE_STORAGE_ROOT = Path(".kela_knowledge").resolve()

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


def get_kb_storage_dir(kb_id: str) -> Path:
    """Return secure, isolated filesystem directory for a knowledge base."""
    safe_id = sanitize_filename(kb_id)
    target = KNOWLEDGE_STORAGE_ROOT / safe_id
    target.mkdir(parents=True, exist_ok=True)
    return target


# =========================================================================
# KNOWLEDGE BASE LIFECYCLE
# =========================================================================

def create_knowledge_base(
    name: str,
    description: str = "",
    owner_project: str = "default",
    embedding_model: str = "local-fast",
    embedding_dim: int = 128,
    kb_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new isolated knowledge base record and directory."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Knowledge base name cannot be blank.")

    generated_id = kb_id or f"kb_{hashlib.md5(clean_name.lower().encode()).hexdigest()[:10]}"
    clean_id = sanitize_filename(generated_id)

    # Initialize directory
    get_kb_storage_dir(clean_id)

    return db_create_kb(
        kb_id=clean_id,
        name=clean_name,
        description=description.strip(),
        owner_project=owner_project.strip(),
        embedding_model=embedding_model.strip(),
        embedding_dim=embedding_dim,
    )


def list_knowledge_bases() -> List[Dict[str, Any]]:
    """List all registered knowledge bases with summary counts."""
    return db_list_kbs()


def get_knowledge_base_details(kb_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve knowledge base metadata and dataset summary."""
    return get_knowledge_base(kb_id)


def delete_knowledge_base(kb_id: str) -> bool:
    """Delete knowledge base, all its datasets, chunks, FTS entries, and disk files."""
    clean_id = sanitize_filename(kb_id)
    if clean_id == "default":
        # Keep default knowledge base container; wipe its contents
        docs = list_knowledge_documents(kb_id="default")
        for d in docs:
            delete_knowledge_document(d["id"])
        storage = get_kb_storage_dir("default")
        shutil.rmtree(storage, ignore_errors=True)
        storage.mkdir(parents=True, exist_ok=True)
        return True

    success = db_delete_kb(clean_id)
    storage = KNOWLEDGE_STORAGE_ROOT / clean_id
    if storage.exists():
        shutil.rmtree(storage, ignore_errors=True)
    return success


# =========================================================================
# DATASET INGESTION & LIFECYCLE
# =========================================================================

def index_file(
    file_path: Path | str,
    kb_id: str = "default",
    source_id: int | None = None,
) -> Dict[str, Any]:
    """
    Ingests and indexes a single document into the specified knowledge base:
    - Validates file boundaries and safe extension
    - Computes content SHA-256 for duplicate skipping
    - Extracts sections with genuine page numbers or sheet names
    - Chunks text while preserving source metadata
    - Generates embeddings using knowledge base's configured provider
    - Stores document, chunks, and FTS5 entries in SQLite
    """
    path = Path(file_path).resolve()
    validate_file_safety(path)

    # Verify knowledge base exists
    kb = get_knowledge_base(kb_id)
    if not kb:
        create_knowledge_base(name=kb_id.title(), kb_id=kb_id)
        kb = get_knowledge_base(kb_id)

    target_dim = kb.get("embedding_dim", 128) if kb else 128
    target_model = kb.get("embedding_model", "local-fast") if kb else "local-fast"

    current_hash = _file_hash(path)
    file_path_str = str(path)

    # Duplicate check: skip if identical content is already indexed in this KB
    existing = get_knowledge_document_by_path(file_path_str, kb_id=kb_id)
    if existing and existing["content_hash"] == current_hash and existing["status"] == "indexed":
        return {
            "status": "skipped",
            "reason": "unchanged",
            "document_id": existing["id"],
            "title": existing["title"],
            "chunk_count": existing["chunk_count"],
            "kb_id": kb_id,
        }

    try:
        sections, mime_type, meta = parse_document_sections(path)
    except Exception as exc:
        logger.error("Failed to parse document %s: %s", path.name, exc)
        doc_id = upsert_knowledge_document(
            file_path=file_path_str,
            title=path.name,
            content_hash=current_hash,
            mime_type="unknown",
            size_bytes=path.stat().st_size,
            chunk_count=0,
            kb_id=kb_id,
            source_id=source_id,
            status="failed",
            error_message=str(exc),
        )
        return {
            "status": "failed",
            "document_id": doc_id,
            "title": path.name,
            "error": str(exc),
            "kb_id": kb_id,
        }

    # Split into chunks retaining page numbers & sheet names
    chunks = chunk_sections(sections, chunk_size=800, overlap=150)

    # Generate embeddings
    for chunk in chunks:
        chunk["embedding"] = generate_local_embedding(chunk["content"], dim=target_dim)

    doc_id = upsert_knowledge_document(
        file_path=file_path_str,
        title=path.name,
        content_hash=current_hash,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        chunk_count=len(chunks),
        kb_id=kb_id,
        source_id=source_id,
        status="indexed",
        error_message=None,
    )

    save_knowledge_chunks(doc_id, chunks, kb_id=kb_id)

    return {
        "status": "indexed",
        "document_id": doc_id,
        "title": path.name,
        "chunk_count": len(chunks),
        "mime_type": mime_type,
        "kb_id": kb_id,
        "embedding_model": target_model,
        "embedding_dim": target_dim,
    }


def ingest_uploaded_file(
    filename: str,
    content_bytes: bytes,
    kb_id: str = "default",
) -> Dict[str, Any]:
    """
    Safely stores an uploaded file into the KB directory and triggers indexing.
    Protects against path traversal, oversized payloads, and code injection.
    """
    clean_name = sanitize_filename(filename)
    if not clean_name:
        raise ValueError("Invalid filename.")

    if len(content_bytes) > 50 * 1024 * 1024:
        raise ValueError("File size exceeds 50 MB limit.")

    kb_dir = get_kb_storage_dir(kb_id)
    content_hash = hashlib.sha256(content_bytes).hexdigest()[:12]
    safe_disk_name = f"{content_hash}_{clean_name}"
    target_path = kb_dir / safe_disk_name

    target_path.write_bytes(content_bytes)

    try:
        res = index_file(target_path, kb_id=kb_id)
        res["uploaded_as"] = clean_name
        return res
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        raise


def index_directory(
    dir_path: Path | str,
    kb_id: str = "default",
    source_id: int | None = None,
    recursive: bool = True,
) -> Dict[str, Any]:
    """Indexes all supported documents within a local directory into the knowledge base."""
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
                res = index_file(item, kb_id=kb_id, source_id=source_id)
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
        "kb_id": kb_id,
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:10],
    }


def reindex_knowledge_base(kb_id: str) -> Dict[str, Any]:
    """Re-reads and re-embeds all existing documents in a knowledge base."""
    docs = list_knowledge_documents(kb_id=kb_id)
    reindexed = 0
    failed = 0
    errors = []

    for d in docs:
        p = Path(d["file_path"])
        if p.is_file():
            try:
                res = index_file(p, kb_id=kb_id)
                if res["status"] in ("indexed", "skipped"):
                    reindexed += 1
                else:
                    failed += 1
                    errors.append(f"{d['title']}: {res.get('error')}")
            except Exception as e:
                failed += 1
                errors.append(f"{d['title']}: {str(e)}")
        else:
            failed += 1
            errors.append(f"{d['title']}: File missing on disk at {d['file_path']}")

    return {
        "kb_id": kb_id,
        "total_documents": len(docs),
        "reindexed": reindexed,
        "failed": failed,
        "errors": errors[:10],
    }


# =========================================================================
# HYBRID RETRIEVAL & CITATION ENGINE
# =========================================================================

def search_knowledge_base(
    query: str,
    kb_id: str = "default",
    top_k: int = 5,
    hybrid: bool = True,
    threshold: float = 0.25,
) -> List[Dict[str, Any]]:
    """
    Multi-dataset hybrid retrieval engine:
    - Filters strictly to the requested knowledge base (strict isolation!)
    - Performs BM25 lexical search via SQLite FTS5
    - Performs vector cosine similarity search
    - Merges rankings via Reciprocal Rank Fusion (RRF)
    - Returns structured chunks with genuine source citations (page, sheet, line numbers)
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    clean_kb_id = kb_id.strip() or "default"

    # 1. Lexical search using SQLite FTS5 confined to this kb_id
    fts_results = search_knowledge_chunks_fts(cleaned_query, kb_id=clean_kb_id, limit=top_k * 3)
    fts_map: Dict[int, Dict[str, Any]] = {}
    for rank, row in enumerate(fts_results, start=1):
        c_id = int(row["chunk_id"])
        fts_map[c_id] = {
            "chunk_id": c_id,
            "document_id": row["document_id"],
            "title": row["title"],
            "file_path": row["file_path"],
            "content": row["content"],
            "chunk_index": row["chunk_index"],
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
            "page_number": row.get("page_number"),
            "sheet_name": row.get("sheet_name"),
            "fts_rank": rank,
        }

    # 2. Semantic vector search confined to this kb_id
    kb = get_knowledge_base(clean_kb_id)
    target_dim = kb.get("embedding_dim", 128) if kb else 128
    query_vec = generate_local_embedding(cleaned_query, dim=target_dim)

    all_chunks = get_all_chunks_with_embeddings(kb_id=clean_kb_id)
    vec_scores: List[tuple[float, Dict[str, Any]]] = []

    for item in all_chunks:
        sim = cosine_similarity(query_vec, item["embedding"])
        if sim >= threshold:
            vec_scores.append((sim, item))

    vec_scores.sort(key=lambda x: x[0], reverse=True)
    vec_map: Dict[int, tuple[int, float, Dict[str, Any]]] = {}
    for rank, (score, item) in enumerate(vec_scores[: top_k * 3], start=1):
        c_id = item["chunk_id"]
        vec_map[c_id] = (rank, score, item)

    # 3. Hybrid Reciprocal Rank Fusion (RRF)
    all_chunk_ids = set(fts_map.keys()) | set(vec_map.keys())
    if not all_chunk_ids:
        return []

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
                    "start_line": vec_item.get("start_line"),
                    "end_line": vec_item.get("end_line"),
                    "page_number": vec_item.get("page_number"),
                    "sheet_name": vec_item.get("sheet_name"),
                }

        if meta:
            ranked_chunks.append((score, meta))

    ranked_chunks.sort(key=lambda x: x[0], reverse=True)

    results = []
    for idx, (score, item) in enumerate(ranked_chunks[:top_k], start=1):
        content = item["content"]
        snippet = content[:280] + ("..." if len(content) > 280 else "")

        citation_dict = {
            "citation_id": f"[{idx}]",
            "kb_id": clean_kb_id,
            "document_id": item["document_id"],
            "title": item["title"],
            "file_path": item["file_path"],
            "chunk_index": item["chunk_index"],
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
            "page_number": item.get("page_number"),
            "sheet_name": item.get("sheet_name"),
            "snippet": snippet,
            "content": content,
            "score": round(score, 4),
        }
        results.append(citation_dict)

    return results


def delete_indexed_document(doc_id: int) -> bool:
    """Deletes an indexed document and removes its safe copy on disk if present."""
    doc = get_knowledge_document(doc_id)
    if not doc:
        return False

    success = delete_knowledge_document(doc_id)

    # If the file was in managed storage (.kela_knowledge), delete physical file
    f_path = Path(doc["file_path"])
    try:
        if KNOWLEDGE_STORAGE_ROOT in f_path.resolve().parents:
            f_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("Could not remove file on disk: %s", exc)

    return success


def list_indexed_documents(kb_id: str | None = None) -> List[Dict[str, Any]]:
    """Lists indexed documents in a knowledge base."""
    return list_knowledge_documents(kb_id=kb_id)


def get_document_details(doc_id: int) -> Optional[Dict[str, Any]]:
    """Fetches document metadata along with all associated chunk records."""
    doc = get_knowledge_document(doc_id)
    if not doc:
        return None
    chunks = get_knowledge_chunks(doc_id)
    doc["chunks"] = chunks
    return doc
