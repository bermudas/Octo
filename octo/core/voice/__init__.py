"""Local voice engine — in-process TTS/STT without HTTP overhead.

Requires one or both optional extras:
  STT only: pip install faster-whisper  (or mlx-whisper on Apple Silicon)
  TTS only: pip install parler_tts soundfile
  Both:     pip install octo-agent[voice]
"""
from __future__ import annotations


def stt_available() -> bool:
    """Return True if a local STT backend (faster-whisper or mlx-whisper) is importable."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def tts_available() -> bool:
    """Return True if local TTS deps (parler_tts, soundfile) are importable."""
    try:
        import parler_tts  # noqa: F401
        import soundfile  # noqa: F401
        return True
    except ImportError:
        return False


def is_available() -> bool:
    """Return True if any local voice backend (STT or TTS) is importable."""
    return stt_available() or tts_available()


async def local_synthesize(
    text: str, voice: str = "Jon", instruct: str | None = None,
    language: str | None = None,
) -> bytes:
    """Synthesize text to WAV bytes using local ParlerTTS.

    Voices: Jon (default male), Laura (female), Gary (deep male), Lea (bright female).
    Old names (Ryan, Vivian) and OpenAI aliases still work.
    """
    from octo.core.voice.tts import synthesize
    return await synthesize(text, voice, instruct=instruct, language=language)


async def local_synthesize_multi(
    segments: list[dict], pause_ms: int = 300,
) -> bytes:
    """Multi-voice synthesis. Each segment: {text, voice, instruct?}."""
    from octo.core.voice.tts import synthesize_multi
    return await synthesize_multi(segments, pause_ms=pause_ms)


async def local_transcribe(audio_data: bytes) -> str:
    """Transcribe audio bytes to text using local Whisper."""
    from octo.core.voice.stt import transcribe
    return await transcribe(audio_data)
