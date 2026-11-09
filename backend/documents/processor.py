"""
Nexus AI — Advanced Document Intelligence Processor
Multi-format document parsing engine supporting:
- PDF: Page-by-page extraction, per-page citations [Page X], text operators.
- DOCX: Native ZIP/XML paragraph, heading, and table extraction without dependencies.
- XLSX: Multi-sheet parsing, column headers, and data formatting.
- CSV / JSON: Structured schema analysis and sample preview.
"""

import csv
import io
import json
import logging
import mimetypes
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any

logger = logging.getLogger("nexus.documents")


def extract_pdf_pages(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """
    Extracts text streams from PDF and attempts to partition them into pages.
    Each page dict contains {'page_number': int, 'text': str}.
    """
    pages: list[dict[str, Any]] = []

    # Method 1: Look for explicit /Page markers or split streams
    stream_pattern = re.compile(b"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    raw_streams = stream_pattern.findall(pdf_bytes)

    page_texts: list[str] = []
    current_stream_texts: list[str] = []

    for raw_stream in raw_streams:
        try:
            decompressed = zlib.decompress(raw_stream)
        except Exception:
            decompressed = raw_stream

        try:
            stream_str = decompressed.decode("latin1", errors="ignore")
            # Extract text within parentheses: (Text) Tj or ' or "
            tj_matches = re.findall(r"\((.*?)\)\s*(?:Tj|'|\")", stream_str)
            for m in tj_matches:
                cleaned = m.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
                cleaned = cleaned.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
                if cleaned.strip():
                    current_stream_texts.append(cleaned)

            # Match array strings [(...)] TJ
            array_matches = re.findall(r"\[(.*?)\]\s*TJ", stream_str)
            for arr in array_matches:
                inner_strings = re.findall(r"\((.*?)\)", arr)
                for s in inner_strings:
                    cleaned = s.replace(r"\(", "(").replace(r"\)", ")")
                    if cleaned.strip():
                        current_stream_texts.append(cleaned)

            # Check if this stream represents a page or segment
            if len(current_stream_texts) > 20:
                page_texts.append(" ".join(current_stream_texts))
                current_stream_texts = []
        except Exception:
            continue

    if current_stream_texts:
        page_texts.append(" ".join(current_stream_texts))

    # If stream parsing gave no results, fallback to ASCII string extraction
    if not page_texts:
        printable = re.findall(rb"[\x20-\x7E\r\n\t]{4,}", pdf_bytes)
        fallback_text = " ".join(p.decode("latin1", errors="ignore") for p in printable)
        if fallback_text.strip():
            page_texts.append(fallback_text)

    # Format into page objects with page numbers
    for idx, pt in enumerate(page_texts, start=1):
        clean_pt = re.sub(r"\s+", " ", pt).strip()
        if clean_pt:
            pages.append({
                "page_number": idx,
                "text": clean_pt,
                "citation": f"[Page {idx}]",
            })

    if not pages:
        pages.append({
            "page_number": 1,
            "text": "Empty or encrypted PDF document.",
            "citation": "[Page 1]",
        })

    return pages


def extract_docx_content(docx_bytes: bytes) -> dict[str, Any]:
    """
    Extracts text paragraphs and tables from a .docx file using standard library zipfile & XML.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            if "word/document.xml" not in z.namelist():
                return {"text": "Invalid DOCX format: missing word/document.xml", "paragraphs": [], "tables": []}

            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)

            # Word XML namespace
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

            paragraphs = []
            tables = []

            # Extract body elements
            body = tree.find("w:body", ns)
            if body is not None:
                for child in body:
                    tag = child.tag.split("}")[-1]
                    if tag == "p":
                        # Paragraph
                        texts = [t.text for t in child.findall(".//w:t", ns) if t.text]
                        p_str = "".join(texts).strip()
                        if p_str:
                            paragraphs.append(p_str)
                    elif tag == "tbl":
                        # Table
                        table_rows = []
                        for tr in child.findall("w:tr", ns):
                            row_cells = []
                            for tc in tr.findall("w:tc", ns):
                                cell_texts = [t.text for t in tc.findall(".//w:t", ns) if t.text]
                                row_cells.append("".join(cell_texts).strip())
                            table_rows.append(row_cells)
                        if table_rows:
                            tables.append(table_rows)

            full_text_lines = paragraphs.copy()
            for t_idx, tbl in enumerate(tables, start=1):
                full_text_lines.append(f"\n--- [Table {t_idx}] ---")
                for r in tbl:
                    full_text_lines.append("| " + " | ".join(r) + " |")

            return {
                "text": "\n\n".join(full_text_lines),
                "paragraphs": paragraphs,
                "tables": tables,
                "paragraph_count": len(paragraphs),
                "table_count": len(tables),
            }
    except Exception as exc:
        logger.error(f"Failed to parse DOCX: {exc}")
        return {"text": f"Error parsing DOCX: {exc}", "paragraphs": [], "tables": []}


def extract_xlsx_content(xlsx_bytes: bytes, max_rows: int = 50) -> dict[str, Any]:
    """
    Extracts sheets and tabular data from an .xlsx file using standard library zipfile & XML.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
            names = z.namelist()

            # 1. Parse shared strings if present
            shared_strings = []
            if "xl/sharedStrings.xml" in names:
                s_tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                ns_s = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in s_tree.findall(".//s:si", ns_s) or s_tree.findall(".//si"):
                    t = si.find(".//s:t", ns_s) if si.find(".//s:t", ns_s) is not None else si.find(".//t")
                    shared_strings.append(t.text if t is not None and t.text else "")

            # 2. Parse worksheets
            sheet_files = [n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            sheets = []

            for sf in sorted(sheet_files):
                sheet_num = sf.replace("xl/worksheets/sheet", "").replace(".xml", "")
                sheet_xml = z.read(sf)
                w_tree = ET.fromstring(sheet_xml)
                ns_w = {"w": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

                sheet_rows = []
                for row_el in w_tree.findall(".//w:row", ns_w) or w_tree.findall(".//row"):
                    row_data = []
                    for c in row_el.findall(".//w:c", ns_w) or row_el.findall(".//c"):
                        cell_type = c.attrib.get("t", "")
                        v_el = c.find(".//w:v", ns_w) if c.find(".//w:v", ns_w) is not None else c.find(".//v")
                        val = v_el.text if v_el is not None and v_el.text else ""

                        if cell_type == "s" and val.isdigit() and int(val) < len(shared_strings):
                            row_data.append(shared_strings[int(val)])
                        else:
                            row_data.append(val)
                    if any(row_data):
                        sheet_rows.append(row_data)

                sheets.append({
                    "sheet_name": f"Sheet {sheet_num}",
                    "row_count": len(sheet_rows),
                    "rows": sheet_rows[:max_rows],
                })

            # Format markdown summary
            text_parts = [f"Excel Workbook: {len(sheets)} sheets."]
            for s in sheets:
                text_parts.append(f"\n### [{s['sheet_name']}] ({s['row_count']} rows)")
                for r in s["rows"][:10]:
                    text_parts.append("| " + " | ".join(r) + " |")

            return {
                "text": "\n".join(text_parts),
                "sheets": sheets,
                "sheet_count": len(sheets),
            }
    except Exception as exc:
        logger.error(f"Failed to parse XLSX: {exc}")
        return {"text": f"Error parsing XLSX: {exc}", "sheets": []}


def extract_pptx_slides(pptx_bytes: bytes) -> dict[str, Any]:
    """
    Extracts text, slide titles, tables, and notes from PPTX presentation without external dependencies.
    Partitions slides into structured [Slide X] blocks for accurate citation.
    """
    slides: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as zf:
            slide_names = [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]

            def slide_sort_key(name: str) -> int:
                m = re.search(r"slide(\d+)\.xml", name)
                return int(m.group(1)) if m else 0

            slide_names.sort(key=slide_sort_key)

            for idx, s_name in enumerate(slide_names, 1):
                try:
                    xml_data = zf.read(s_name)
                    tree = ET.fromstring(xml_data)
                except Exception:
                    continue

                paragraphs: list[str] = []
                for p in tree.iter():
                    if p.tag.endswith("}p"):
                        p_texts = [t.text for t in p.iter() if t.tag.endswith("}t") and t.text]
                        combined = "".join(p_texts).strip()
                        if combined:
                            paragraphs.append(combined)

                # Check for tables
                table_lines: list[str] = []
                for tbl in tree.iter():
                    if tbl.tag.endswith("}tbl"):
                        for tr in tbl.iter():
                            if tr.tag.endswith("}tr"):
                                row_cells = []
                                for tc in tr.iter():
                                    if tc.tag.endswith("}tc"):
                                        c_texts = [t.text for t in tc.iter() if t.tag.endswith("}t") and t.text]
                                        row_cells.append("".join(c_texts).strip())
                                if row_cells and any(row_cells):
                                    table_lines.append("| " + " | ".join(row_cells) + " |")

                # Slide title & content
                title = paragraphs[0] if paragraphs else f"Slide {idx}"
                body_paragraphs = paragraphs[1:] if len(paragraphs) > 1 else paragraphs

                slide_body_parts = []
                if body_paragraphs:
                    slide_body_parts.extend(body_paragraphs)
                if table_lines:
                    slide_body_parts.append("\nTables:\n" + "\n".join(table_lines))

                slide_text = "\n".join(slide_body_parts) if slide_body_parts else title
                citation = f"[Slide {idx}]"

                slides.append({
                    "slide_number": idx,
                    "citation": citation,
                    "title": title,
                    "text": slide_text,
                    "paragraphs": paragraphs,
                })
    except Exception as exc:
        logger.warning("Error unpacking PPTX slides: %s", exc)

    formatted_slides = []
    for s in slides:
        formatted_slides.append(f"### {s['citation']} - {s['title']}\n{s['text']}")

    combined_text = "\n\n".join(formatted_slides) if formatted_slides else "Empty or unparseable presentation."
    return {
        "slide_count": len(slides),
        "slides": slides,
        "text": combined_text,
    }


def process_document(file_path: Path | str) -> dict[str, Any]:
    """
    Unified entry point for document intelligence.
    Returns rich metadata, structured content, page citations, and tabular data.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise ValueError(f"File does not exist: {path}")

    suffix = path.suffix.lower()
    raw_bytes = path.read_bytes()
    mime, _ = mimetypes.guess_type(str(path))
    size_bytes = len(raw_bytes)

    if suffix == ".pdf":
        pages = extract_pdf_pages(raw_bytes)
        combined_text = "\n\n".join(f"--- {p['citation']} ---\n{p['text']}" for p in pages)
        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "application/pdf",
            "size_bytes": size_bytes,
            "document_type": "pdf",
            "total_pages": len(pages),
            "pages": pages,
            "content": combined_text,
            "citations_available": True,
        }

    elif suffix in {".docx", ".doc"}:
        res = extract_docx_content(raw_bytes)
        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size_bytes": size_bytes,
            "document_type": "docx",
            "total_paragraphs": res.get("paragraph_count", 0),
            "total_tables": res.get("table_count", 0),
            "content": res["text"],
            "citations_available": False,
        }

    elif suffix in {".xlsx", ".xls"}:
        res = extract_xlsx_content(raw_bytes)
        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size_bytes": size_bytes,
            "document_type": "xlsx",
            "sheets": res.get("sheets", []),
            "total_sheets": res.get("sheet_count", 0),
            "content": res["text"],
            "citations_available": True,
        }

    elif suffix in {".pptx", ".ppt"}:
        res = extract_pptx_slides(raw_bytes)
        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "size_bytes": size_bytes,
            "document_type": "presentation",
            "slides": res.get("slides", []),
            "total_slides": res.get("slide_count", 0),
            "content": res["text"],
            "citations_available": True,
        }

    elif suffix == ".csv":
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")

        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        headers = rows[0] if rows else []
        row_count = max(0, len(rows) - 1)

        summary_lines = [
            f"CSV File: {path.name} ({row_count} rows, {len(headers)} columns)",
            f"Headers: {', '.join(headers)}",
            "",
            "Preview:",
        ]
        for r in rows[:15]:
            summary_lines.append("| " + " | ".join(r) + " |")

        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "text/csv",
            "size_bytes": size_bytes,
            "document_type": "csv",
            "headers": headers,
            "row_count": row_count,
            "content": "\n".join(summary_lines),
            "citations_available": False,
        }

    elif suffix == ".json":
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")

        try:
            data = json.loads(text)
            formatted = json.dumps(data, indent=2)[:5000]
            summary = f"JSON Document: {type(data).__name__} structure with {len(data) if isinstance(data, (dict, list)) else 1} top-level entries.\n\n{formatted}"
        except Exception:
            summary = text[:5000]

        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "application/json",
            "size_bytes": size_bytes,
            "document_type": "json",
            "content": summary,
            "citations_available": False,
        }

    else:
        # Default plain text / code / markdown
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")

        return {
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": mime or "text/plain",
            "size_bytes": size_bytes,
            "document_type": "text",
            "content": text,
            "citations_available": False,
        }
