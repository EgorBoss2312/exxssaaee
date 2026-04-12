def chunk_text(text: str, max_chars: int = 700, overlap: int = 120) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        piece = text[start:end]
        if piece.strip():
            chunks.append(piece.strip())
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks
