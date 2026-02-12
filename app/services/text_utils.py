import re
from typing import Any, Dict, List

def normalize_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    text = re.sub(r"([.!?])\s+", r"\1\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def chunk_text(text: str, max_chars: int = 6000) -> List[str]:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"\n\s*\n", text)
    chunks: List[str] = []
    buff = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buff) + len(p) + 2 <= max_chars:
            buff = (buff + "\n\n" + p).strip() if buff else p
        else:
            if buff:
                chunks.append(buff)
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i:i + max_chars])
                buff = ""
            else:
                buff = p
    if buff:
        chunks.append(buff)
    return chunks
