import tempfile
from typing import Any, Dict, List, Optional, Tuple
import streamlit as st
import whisper

@st.cache_resource
def get_whisper_model(model_name: str):
    return whisper.load_model(model_name)

def transcribe_video_bytes(
    video_bytes: bytes,
    whisper_model: str = "small",
    language: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Transcreve bytes de vídeo usando openai-whisper (local).
    Retorna (texto, segments).
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(video_bytes)
        temp_path = tmp.name

    model = get_whisper_model(whisper_model)
    kwargs = {}
    if language:
        kwargs["language"] = language
    result = model.transcribe(temp_path, **kwargs)
    text = (result.get("text") or "").strip()
    segments = result.get("segments") or []
    return text, segments
