from typing import Optional, List, Tuple
import streamlit as st

@st.cache_resource
def load_whisper_model(name: str):
    import whisper
    return whisper.load_model(name)

def transcribe_video_bytes(video_bytes: bytes, whisper_model: str = "base", language: Optional[str] = None) -> Tuple[str, List[dict]]:
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
        f.write(video_bytes)
        tmp_path = f.name
    try:
        model = load_whisper_model(whisper_model)
        result = model.transcribe(tmp_path, language=language) if language else model.transcribe(tmp_path)
        text = (result.get("text") or "").strip()
        segments = result.get("segments") or []
        norm = []
        for s in segments:
            norm.append({
                "id": s.get("id"),
                "start": s.get("start"),
                "end": s.get("end"),
                "text": (s.get("text") or "").strip(),
            })
        return text, norm
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
