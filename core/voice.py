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


def decode_audio(path: str, sampling_rate: int = 16000):
    """Decode any audio file (Telegram voice notes are Opus in Ogg) to 16 kHz mono float32.

    faster-whisper's own decoder passes an option that newer PyAV versions removed
    ('metadata_errors'), so we decode here and hand it the raw samples instead.
    """
    import av
    import numpy as np

    chunks = []
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    with av.open(path, mode="r") as container:
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            frame.pts = None
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(path: str) -> tuple:
    """Returns (text, language). Blocking; run in a thread."""
    model = _get_model()
    audio = decode_audio(path)
    if audio.size == 0:
        return "", ""
    segments, info = model.transcribe(audio, beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, getattr(info, "language", "")
