"""Voice note transcription on this computer with faster-whisper (free, private).

The model downloads once (~150 MB for 'base') the first time a voice note arrives.
Set WHISPER_MODEL=small in .env for better accuracy on mixed Tamil/Hindi/English (~480 MB).
"""
import os
import threading

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
MAX_SECONDS = int(os.getenv("VOICE_MAX_SECONDS", "300"))

_model = None
_lock = threading.Lock()


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        return _model


def transcribe(path: str) -> tuple:
    """Returns (text, language). Blocking; run in a thread."""
    model = _get_model()
    segments, info = model.transcribe(path, beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, getattr(info, "language", "")
