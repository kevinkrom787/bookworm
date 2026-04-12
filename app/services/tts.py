"""
TTS service — wraps Kokoro-ONNX for text-to-speech.

Kokoro-ONNX (MIT/Apache 2.0) runs on CPU, optimized for edge devices like Pi 5.
When Kokoro is not installed, a stub returns a silent WAV so the UI still works
during development. Install when you're ready:

    pip install kokoro-onnx soundfile

Weights (~80MB) are downloaded automatically on first synthesis call.

Voice options (all English):
  af_heart  — American female, warm (default, good for kids)
  af_bella  — American female, bright
  am_adam   — American male, calm
  bf_emma   — British female, clear
  bm_daniel — British male, warm
"""

import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class WordTiming:
    word: str
    start_ms: int
    end_ms: int
    word_index: int  # position in the original word list (0-based)


@dataclass
class TTSResult:
    audio_bytes: bytes    # WAV file bytes — send directly to browser
    sample_rate: int
    duration_ms: int
    word_timings: list[WordTiming]
    voice: str
    is_stub: bool = False  # True when Kokoro is not installed


class TTSService:
    VOICES = {
        "af_heart": "American Female — warm",
        "af_bella": "American Female — bright",
        "am_adam": "American Male — calm",
        "bf_emma": "British Female — clear",
        "bm_daniel": "British Male — warm",
    }

    def __init__(
        self,
        model_path: Optional[Path] = None,
        voices_path: Optional[Path] = None,
    ):
        self._kokoro = None
        self._model_path = model_path
        self._voices_path = voices_path
        self._available = self._probe()

    def _probe(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            import soundfile    # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def is_available(self) -> bool:
        return self._available

    def _load_kokoro(self):
        """Lazy-load Kokoro model on first use (avoids slow startup)."""
        if self._kokoro is not None:
            return self._kokoro
        from kokoro_onnx import Kokoro
        model = str(self._model_path) if self._model_path else "kokoro-v1.0.onnx"
        voices = str(self._voices_path) if self._voices_path else "voices-v1.0.bin"
        self._kokoro = Kokoro(model, voices)
        return self._kokoro

    def synthesize(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
    ) -> TTSResult:
        """
        Convert text to speech. Returns a TTSResult with WAV bytes and word timings.
        Falls back to a silent stub WAV if Kokoro is not installed.
        """
        # Safety: cap at ~500 words per call to avoid memory issues on Pi
        words = text.split()
        if len(words) > 500:
            text = " ".join(words[:500])

        if self._available:
            return self._synth_kokoro(text, voice, speed)
        return self._synth_stub(text)

    def _synth_kokoro(self, text: str, voice: str, speed: float) -> TTSResult:
        import soundfile as sf
        kokoro = self._load_kokoro()
        samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")

        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format="WAV")
        audio_bytes = buf.getvalue()
        duration_ms = int(len(samples) / sample_rate * 1000)

        return TTSResult(
            audio_bytes=audio_bytes,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            word_timings=_estimate_word_timings(text, duration_ms),
            voice=voice,
            is_stub=False,
        )

    def _synth_stub(self, text: str) -> TTSResult:
        """
        Silent WAV stub — lets the UI run without Kokoro installed.
        Word highlighting still works via estimated timing.
        To activate real TTS: pip install kokoro-onnx soundfile
        """
        words = text.split()
        duration_ms = max(len(words) * 380, 1000)  # ~158 WPM
        sample_rate = 22050
        num_samples = int(sample_rate * duration_ms / 1000)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * num_samples)

        return TTSResult(
            audio_bytes=buf.getvalue(),
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            word_timings=_estimate_word_timings(text, duration_ms),
            voice="stub",
            is_stub=True,
        )


def _estimate_word_timings(text: str, total_duration_ms: int) -> list[WordTiming]:
    """
    Distribute duration across words proportionally by character length.
    Longer words get slightly more time — a reasonable approximation.
    When Kokoro phoneme timing is available, we'll swap this out.
    """
    raw_words = text.split()
    if not raw_words:
        return []

    total_chars = sum(len(w) for w in raw_words)
    if total_chars == 0:
        return []

    timings = []
    cursor_ms = 0
    for i, word in enumerate(raw_words):
        proportion = len(word) / total_chars
        word_ms = max(1, int(total_duration_ms * proportion))
        timings.append(WordTiming(
            word=word,
            start_ms=cursor_ms,
            end_ms=cursor_ms + word_ms,
            word_index=i,
        ))
        cursor_ms += word_ms

    return timings
