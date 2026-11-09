import re


def chunk_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[dict]:
    """
    Split text into overlapping chunks, attempting to break cleanly on
    paragraphs, code blocks, headings, or sentences.
    Returns list of dicts: {chunk_index, content, start_line, end_line, token_count}.
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        return []

    lines = cleaned_text.splitlines()
    if not lines:
        return []

    # Map each line to its character offset in the joined text
    line_offsets = []
    current_char = 0
    for line in lines:
        line_offsets.append((current_char, current_char + len(line)))
        current_char += len(line) + 1  # newline

    def get_line_range(start_char: int, end_char: int) -> tuple[int, int]:
        s_line = 1
        e_line = len(lines)
        for i, (lo, hi) in enumerate(line_offsets, start=1):
            if lo <= start_char <= hi or lo >= start_char:
                s_line = i
                break
        for i in range(len(line_offsets) - 1, -1, -1):
            lo, hi = line_offsets[i]
            if lo <= end_char <= hi or hi <= end_char:
                e_line = i + 1
                break
        return s_line, max(s_line, e_line)

    chunks = []
    # Break into logical segments (paragraphs / markdown blocks)
    segments = re.split(r"(\n\s*\n+)", cleaned_text)
    
    current_chunk = ""
    chunk_start_char = 0
    current_char_pos = 0

    for segment in segments:
        seg_len = len(segment)
        if len(current_chunk) + seg_len <= chunk_size:
            if not current_chunk:
                chunk_start_char = current_char_pos
            current_chunk += segment
        else:
            # Current chunk has reached target size
            if current_chunk.strip():
                start_l, end_l = get_line_range(
                    chunk_start_char,
                    chunk_start_char + len(current_chunk),
                )
                chunks.append({
                    "chunk_index": len(chunks),
                    "content": current_chunk.strip(),
                    "start_line": start_l,
                    "end_line": end_l,
                    "token_count": len(current_chunk.split()),
                })
                # Overlap: keep the tail of current_chunk
                if overlap > 0 and len(current_chunk) > overlap:
                    tail = current_chunk[-overlap:]
                    # Break at space if possible
                    space_idx = tail.find(" ")
                    if space_idx != -1:
                        tail = tail[space_idx + 1:]
                    current_chunk = tail + segment
                    chunk_start_char = current_char_pos - len(tail)
                else:
                    current_chunk = segment
                    chunk_start_char = current_char_pos
            else:
                # Segment alone is larger than chunk_size
                # Split large segment by sentences or fixed length
                for idx in range(0, seg_len, max(1, chunk_size - overlap)):
                    sub_seg = segment[idx : idx + chunk_size]
                    if sub_seg.strip():
                        start_l, end_l = get_line_range(
                            current_char_pos + idx,
                            current_char_pos + idx + len(sub_seg),
                        )
                        chunks.append({
                            "chunk_index": len(chunks),
                            "content": sub_seg.strip(),
                            "start_line": start_l,
                            "end_line": end_l,
                            "token_count": len(sub_seg.split()),
                        })
                current_chunk = ""
                chunk_start_char = current_char_pos + seg_len

        current_char_pos += seg_len

    if current_chunk.strip():
        start_l, end_l = get_line_range(
            chunk_start_char,
            chunk_start_char + len(current_chunk),
        )
        chunks.append({
            "chunk_index": len(chunks),
            "content": current_chunk.strip(),
            "start_line": start_l,
            "end_line": end_l,
            "token_count": len(current_chunk.split()),
        })

    return chunks
