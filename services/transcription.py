from typing import Optional, Tuple, List

def transcribe_video_bytes(video_bytes: bytes, whisper_model: str = "base", language: Optional[str] = None) -> Tuple[str, List[dict]]:
    import tempfile, os
    import whisper
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
        f.write(video_bytes)
        tmp_path = f.name
    try:
        model = whisper.load_model(whisper_model)
        result = model.transcribe(tmp_path, language=language) if language else model.transcribe(tmp_path)
        text = (result.get("text") or "").strip()
        segments = result.get("segments") or []
        norm = [{"id": s.get("id"), "start": s.get("start"), "end": s.get("end"), "text": (s.get("text") or "").strip()} for s in segments]
        return text, norm
    finally:
        try: os.remove(tmp_path)
        except Exception: pass
