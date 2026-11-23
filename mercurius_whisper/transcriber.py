"""faster-whisper: one model loaded once, a bounded number of recognitions at a time in the order of coming, silence
kept away from the model, a recognition cut when it runs over the timeout.

ref: references/hermes-agent/tools/transcription_local.py@e96221fa:L228-L264 (build_local_transcribe_kwargs) —
     the settings against hallucinations: Silero VAD, condition_on_previous_text=False, beam 5, the confidence gate
     passed into faster-whisper itself; here they are fixed, not read from a config
ref: references/hermes-agent/tools/transcription_local.py@e96221fa:L273-L295 (_is_hallucinated_segment,
     _join_confident_segments) — a segment is dropped only when it is both non-speech and of low confidence
ref: references/hermes-agent/tools/transcription_local.py@e96221fa:L173-L197 (_create_whisper_model) — the model
     from disk first without contacting the Hub, the download only on a miss
ref: references/hermes-agent/tools/transcription_tools.py@e96221fa:L338-L356 (_get_or_load_local_model) — one load
     for concurrent requests; here the model is loaded once at start and kept (a service, not a CLI), and there is
     no CUDA-to-CPU fallback: the device is the owner's setting
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .config import Settings, normalize_language

logger = logging.getLogger("mercurius_whisper")

SAMPLE_RATE = 16000
_NO_SPEECH_THRESHOLD = 0.6
_LOGPROB_THRESHOLD = -1.0
_VAD_MIN_SILENCE_MS = 500


class NotReady(RuntimeError):
    """The model is still loading or failed to load."""


class AudioError(ValueError):
    """The file is not audio the decoder can read."""


class TimedOut(RuntimeError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"the recognition took over {limit} s")
        self.limit = limit


@dataclass(frozen=True)
class Result:
    text: str
    language: str | None
    seconds: float


class FifoGate:
    """Up to `size` holders at once; the others wait and come in by the order they came."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._busy = 0
        self._line: deque[threading.Event] = deque()
        self._lock = threading.Lock()

    @property
    def waiting(self) -> int:
        with self._lock:
            return len(self._line)

    def enter(self) -> None:
        with self._lock:
            if self._busy < self._size and not self._line:
                self._busy += 1
                return
            turn = threading.Event()
            self._line.append(turn)
        turn.wait()  # leave() hands its place over: _busy stays counted for us

    def leave(self) -> None:
        with self._lock:
            if self._line:
                self._line.popleft().set()
            else:
                self._busy -= 1


def load_model(settings: Settings) -> Any:
    """A WhisperModel from settings.models_dir; downloaded from the Hub only when it is not there yet."""
    from faster_whisper import WhisperModel  # imported here: the tests run without faster-whisper

    kwargs = {
        "device": settings.device,
        "compute_type": settings.compute_type,
        "cpu_threads": settings.threads,
        "download_root": settings.models_dir,
    }
    try:
        return WhisperModel(settings.model, local_files_only=True, **kwargs)
    except OSError:  # not on disk (the Hub's LocalEntryNotFoundError is an OSError)
        pass
    except RuntimeError as exc:  # an interrupted download leaves a folder without the weights
        if "Unable to open file" not in str(exc):
            raise
    logger.info("model %s is not on disk, downloading it", settings.model)
    return WhisperModel(settings.model, local_files_only=False, **kwargs)


def decode_audio(data: bytes) -> Sequence[float]:
    """Mono 16 kHz samples of what PyAV (the FFmpeg libraries) reads: voice .oga/opus, mp3, m4a, wav… in memory:
    the audio is not written to disk."""
    from faster_whisper import decode_audio as decode

    samples: Sequence[float] = decode(io.BytesIO(data), sampling_rate=SAMPLE_RATE)
    return samples


def _hallucinated(segment: Any) -> bool:
    try:
        return float(segment.no_speech_prob) > _NO_SPEECH_THRESHOLD and float(segment.avg_logprob) < _LOGPROB_THRESHOLD
    except (AttributeError, TypeError, ValueError):
        return False


class Transcriber:
    def __init__(
        self,
        settings: Settings,
        load_model: Callable[[Settings], Any] = load_model,
        decode: Callable[[bytes], Sequence[float]] = decode_audio,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._load_model = load_model
        self._decode = decode
        self._clock = clock
        self._model: Any = None
        self._gate = FifoGate(settings.concurrency)
        self.state = "loading"
        self.error: str | None = None

    def load(self) -> None:
        """Load the model; the state becomes ready or failed (with the class of the error, not its text)."""
        try:
            self._model = self._load_model(self._settings)
        except Exception as exc:
            self.state, self.error = "failed", type(exc).__name__
            logger.error("model %s failed to load: %s", self._settings.model, type(exc).__name__)
            return
        self.state = "ready"
        logger.info("model %s is ready", self._settings.model)

    def transcribe(self, data: bytes, language: str | None = None, prompt: str | None = None) -> Result:
        model = self._model
        if self.state != "ready" or model is None:
            raise NotReady(self.state)
        try:
            audio = self._decode(data)
        except (TypeError, AttributeError, ImportError, NameError):
            raise  # a fault of the program, not of the file
        except Exception as exc:  # the decoder's own errors (PyAV) say what is wrong with the file
            raise AudioError(str(exc)[:300] or type(exc).__name__) from None
        kwargs: dict[str, Any] = {
            "beam_size": 5,
            "condition_on_previous_text": False,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": _VAD_MIN_SILENCE_MS},
            "no_speech_threshold": _NO_SPEECH_THRESHOLD,
            "log_prob_threshold": _LOGPROB_THRESHOLD,
        }
        code = self._language(model, language)
        if code is not None:
            kwargs["language"] = code
        if prompt and prompt.strip():
            kwargs["initial_prompt"] = prompt.strip()[:1000]
        self._gate.enter()
        try:
            deadline = self._clock() + self._settings.timeout
            segments, info = model.transcribe(audio, **kwargs)
            kept: list[str] = []
            # transcribe() is lazy: the decoding happens while the segments are iterated, so the time is checked
            # between them (one segment is up to 30 s of audio)
            for segment in segments:
                if self._clock() > deadline:
                    raise TimedOut(self._settings.timeout)
                if not _hallucinated(segment):
                    kept.append(segment.text.strip())
        finally:
            self._gate.leave()
        text = " ".join(part for part in kept if part).strip()
        return Result(text, getattr(info, "language", None), round(len(audio) / SAMPLE_RATE, 2))

    def _language(self, model: Any, requested: str | None) -> str | None:
        """The request's language when the model knows it; auto — detect; otherwise the language of the settings."""
        if requested is not None and requested.strip().lower() == "auto":
            return None
        code = normalize_language(requested)
        supported = getattr(model, "supported_languages", None)
        if code is not None and (not isinstance(supported, (list, tuple, set, frozenset)) or code in supported):
            return code
        return self._settings.language
