import csv
import io
import json
import logging
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from documents.processor import (
    extract_pdf_pages,
    extract_docx_content,
    extract_xlsx_content,
    extract_pptx_slides,
)

logger = logging.getLogger("kela.knowledge.parser")

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB safety limit

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".pdf", ".docx", ".doc",
    ".xlsx", ".xls", ".csv", ".json", ".jsonl", ".py", ".ts",
    ".tsx", ".js", ".html", ".htm", ".yaml", ".yml",
}


@dataclass
class DocumentSection:
    content: str
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    section_title: Optional[str] = None


def sanitize_filename(filename: str) -> str:
    """Strip path traversal elements and unsafe characters from filenames."""
    clean = Path(filename).name
    clean = re.sub(r'[\r\n\t\\/:*?"<>|]', '_', clean)
    clean = clean.strip(" .")
    return clean or "document"


def validate_file_safety(file_path: Path) -> None:
    """Validate file existence, size boundaries, and extension safety."""
    if not file_path.is_file():
        raise ValueError(f"File not found: {file_path}")
    size = file_path.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File '{file_path.name}' exceeds maximum allowed size ({size / (1024*1024):.1f} MB > 50 MB limit)."
        )
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")


def parse_csv_content(content_str: str, max_sample_rows: int = 50) -> str:
    """Parse CSV text into structured markdown table representation."""
    reader = csv.reader(io.StringIO(content_str))
    rows = list(reader)
    if not rows:
        return "Empty CSV document."

    headers = rows[0]
    total_rows = max(0, len(rows) - 1)
    lines = [
        f"CSV Dataset Summary: {total_rows} records across {len(headers)} columns.",
        f"Columns: {', '.join(headers)}",
        "",
        "Preview Data Table:",
    ]

    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    lines.append(header_line)
    lines.append(sep_line)

    for row in rows[1 : max_sample_rows + 1]:
        padded_row = row + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(padded_row[: len(headers)]) + " |")

    if total_rows > max_sample_rows:
        lines.append(f"... ({total_rows - max_sample_rows} additional rows omitted for indexing summary)")

    return "\n".join(lines)


def parse_json_content(content_str: str) -> str:
    """Parse JSON text into formatted readable structure."""
    try:
        data = json.loads(content_str)
        if isinstance(data, list):
            lines = [f"JSON Dataset: Array of {len(data)} items."]
            sample = data[:10]
            lines.append(json.dumps(sample, indent=2, ensure_ascii=False))
            return "\n".join(lines)
        elif isinstance(data, dict):
            lines = [f"JSON Document: Object with {len(data)} root keys ({', '.join(list(data.keys())[:15])})."]
            lines.append(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
            return "\n".join(lines)
    except Exception:
        pass
    return content_str


def parse_jsonl_content(content_str: str) -> str:
    """Parse JSONL (JSON Lines) text into readable structured summaries."""
    lines = [l.strip() for l in content_str.splitlines() if l.strip()]
    records = []
    for l in lines[:25]:
        try:
            records.append(json.loads(l))
        except Exception:
            records.append({"raw": l})
    header = f"JSONL Dataset: {len(lines)} records total."
    preview = json.dumps(records, indent=2, ensure_ascii=False)
    return f"{header}\n\nPreview Records:\n{preview}"


def parse_document_sections(file_path: Path) -> Tuple[List[DocumentSection], str, Dict[str, Any]]:
    """
    Parses a document into fine-grained sections with accurate source attribution:
    - PDF: Section per page with real page_number [Page X]
    - DOCX: Section for paragraphs and tables
    - XLSX: Section per sheet with real sheet_name [Sheet: X]
    - CSV / JSON / JSONL / TXT: Unified structured text section
    Returns: (list of DocumentSection, mime_type, metadata_dict)
    """
    validate_file_safety(file_path)
    suffix = file_path.suffix.lower()
    raw_bytes = file_path.read_bytes()
    mime, _ = mimetypes.guess_type(str(file_path))
    mime = mime or "text/plain"

    sections: List[DocumentSection] = []
    meta: Dict[str, Any] = {
        "file_name": file_path.name,
        "size_bytes": len(raw_bytes),
        "suffix": suffix,
    }

    if suffix == ".pdf":
        pages = extract_pdf_pages(raw_bytes)
        meta["total_pages"] = len(pages)
        for p in pages:
            text = p.get("text", "").strip()
            if text:
                sections.append(DocumentSection(
                    content=text,
                    page_number=p.get("page_number"),
                    section_title=f"Page {p.get('page_number')}",
                ))
        return sections, "application/pdf", meta

    elif suffix in {".docx", ".doc"}:
        res = extract_docx_content(raw_bytes)
        content = res.get("text", "").strip()
        meta["paragraph_count"] = res.get("paragraph_count", 0)
        meta["table_count"] = res.get("table_count", 0)
        if content:
            sections.append(DocumentSection(
                content=content,
                section_title="Document Body",
            ))
        return sections, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", meta

    elif suffix in {".xlsx", ".xls"}:
        res = extract_xlsx_content(raw_bytes)
        sheets = res.get("sheets", [])
        meta["sheet_count"] = len(sheets)
        for s in sheets:
            sheet_title = s.get("sheet_name", "Sheet")
            rows = s.get("rows", [])
            sheet_lines = [f"--- [{sheet_title}] ({len(rows)} rows) ---"]
            for r in rows:
                sheet_lines.append("| " + " | ".join(str(c) for c in r) + " |")
            text = "\n".join(sheet_lines).strip()
            if text:
                sections.append(DocumentSection(
                    content=text,
                    sheet_name=sheet_title,
                    section_title=sheet_title,
                ))
        return sections, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", meta

    elif suffix in {".pptx", ".ppt"}:
        res = extract_pptx_slides(raw_bytes)
        slides = res.get("slides", [])
        meta["slide_count"] = len(slides)
        for s in slides:
            text = s.get("text", "").strip()
            num = s.get("slide_number", 1)
            if text:
                sections.append(DocumentSection(
                    content=text,
                    page_number=num,
                    section_title=f"Slide {num}",
                ))
        return sections, "application/vnd.openxmlformats-officedocument.presentationml.presentation", meta

    # Text-based formats
    try:
        content_str = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_str = raw_bytes.decode("latin-1", errors="replace")

    if suffix == ".csv":
        formatted = parse_csv_content(content_str)
        sections.append(DocumentSection(content=formatted, section_title="CSV Data"))
        return sections, "text/csv", meta

    elif suffix == ".json":
        formatted = parse_json_content(content_str)
        sections.append(DocumentSection(content=formatted, section_title="JSON Data"))
        return sections, "application/json", meta

    elif suffix == ".jsonl":
        formatted = parse_jsonl_content(content_str)
        sections.append(DocumentSection(content=formatted, section_title="JSONL Data"))
        return sections, "application/x-jsonlines", meta

    # Markdown / TXT / Source code
    sections.append(DocumentSection(content=content_str, section_title="Text Document"))
    return sections, mime, meta


def parse_file(file_path: Path) -> Tuple[str, str]:
    """Legacy helper returning full document text string and MIME type."""
    sections, mime, _ = parse_document_sections(file_path)
    combined = "\n\n".join(s.content for s in sections)
    return combined, mime
