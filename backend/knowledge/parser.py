import csv
import io
import mimetypes
import re
import zlib
from pathlib import Path


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Pure-Python basic PDF text stream extractor."""
    text_parts = []
    # Match PDF stream objects: stream ... endstream
    stream_pattern = re.compile(b"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    for match in stream_pattern.finditer(pdf_bytes):
        raw_stream = match.group(1)
        # Try zlib decompress (FlateDecode)
        try:
            decompressed = zlib.decompress(raw_stream)
        except Exception:
            decompressed = raw_stream

        # Extract text within parentheses in PDF text operators: (Text) Tj or [(T)(e)(x)(t)] TJ
        try:
            stream_str = decompressed.decode("latin1", errors="ignore")
            # Match (text) followed by Tj or '
            tj_matches = re.findall(r"\((.*?)\)\s*(?:Tj|'|\")", stream_str)
            for m in tj_matches:
                # Unescape standard PDF escapes
                cleaned = m.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
                cleaned = cleaned.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
                text_parts.append(cleaned)

            # Match array strings [(...)] TJ
            array_matches = re.findall(r"\[(.*?)\]\s*TJ", stream_str)
            for arr in array_matches:
                inner_strings = re.findall(r"\((.*?)\)", arr)
                for s in inner_strings:
                    cleaned = s.replace(r"\(", "(").replace(r"\)", ")")
                    text_parts.append(cleaned)
        except Exception:
            continue

    if text_parts:
        return " ".join(text_parts)

    # Fallback to ASCII printable strings
    printable = re.findall(rb"[\x20-\x7E\r\n\t]{4,}", pdf_bytes)
    return " ".join(p.decode("latin1", errors="ignore") for p in printable)


def parse_csv_content(content_str: str, max_sample_rows: int = 15) -> str:
    """Parse CSV text into a structured, readable markdown summary and sample."""
    reader = csv.reader(io.StringIO(content_str))
    rows = list(reader)
    if not rows:
        return "Empty CSV document."

    headers = rows[0]
    total_rows = len(rows) - 1
    lines = [
        f"CSV Dataset Summary: {total_rows} records across {len(headers)} columns.",
        f"Columns: {', '.join(headers)}",
        "",
        "Sample Data Preview:",
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


def parse_file(file_path: Path) -> tuple[str, str]:
    """
    Parses a file and returns (extracted_text, detected_mime_type).
    Uses the advanced document intelligence processor for rich formats (PDF, PPTX, DOCX, XLSX, CSV, JSON),
    and falls back to safe text extraction for code/text files.
    """
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"File not found: {path}")

    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "text/plain"

    # Use unified document intelligence for structured & binary formats
    if suffix in {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".json"}:
        try:
            from documents.processor import process_document
            doc = process_document(path)
            content = doc.get("content", "")
            detected_mime = doc.get("mime_type", mime)
            if content and content.strip():
                return content, detected_mime
        except Exception:
            pass

    # Safe text decoding for plain text / source code
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="latin-1")
        except Exception as exc:
            raise ValueError(f"File encoding could not be read: {exc}") from exc

    return content, mime
