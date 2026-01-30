"""Transcription module using faster-whisper."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from .settings import get_settings

logger = logging.getLogger(__name__)

# Global model instances (loaded lazily)
_model_fast: WhisperModel | None = None
_model_accurate: WhisperModel | None = None


@dataclass
class TranscriptionResult:
    """Result of ASR transcription."""
    text: str
    segments: list[dict[str, Any]]
    language: str
    avg_logprob: float | None
    no_speech_prob: float | None
    model_name: str


def _load_model(model_name: str) -> WhisperModel:
    """Load a Whisper model with configured settings."""
    settings = get_settings()

    # Set cache directory
    os.environ["HF_HOME"] = settings.whisper_cache_dir

    logger.info(f"Loading Whisper model: {model_name}")

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type=settings.whisper_compute_type,
        cpu_threads=settings.whisper_threads,
        download_root=settings.whisper_cache_dir,
    )

    logger.info(f"Loaded Whisper model: {model_name}")
    return model


def get_model_fast() -> WhisperModel:
    """Get the fast (small) Whisper model."""
    global _model_fast
    if _model_fast is None:
        settings = get_settings()
        _model_fast = _load_model(settings.whisper_model_fast)
    return _model_fast


def get_model_accurate() -> WhisperModel:
    """Get the accurate (larger) Whisper model."""
    global _model_accurate
    if _model_accurate is None:
        settings = get_settings()
        _model_accurate = _load_model(settings.whisper_model_accurate)
    return _model_accurate


def transcribe_audio(
    audio_path: Path,
    model_type: str = "fast",
) -> TranscriptionResult:
    """
    Transcribe audio file using faster-whisper.

    Args:
        audio_path: Path to WAV audio file (16kHz mono recommended)
        model_type: "fast" or "accurate"

    Returns:
        TranscriptionResult with text, segments, and metrics
    """
    settings = get_settings()

    if model_type == "fast":
        model = get_model_fast()
        model_name = settings.whisper_model_fast
    else:
        model = get_model_accurate()
        model_name = settings.whisper_model_accurate

    logger.info(
        f"Starting transcription",
        extra={
            "audio_path": str(audio_path),
            "model": model_name,
            "model_type": model_type,
        },
    )

    # Run transcription
    segments_gen, info = model.transcribe(
        str(audio_path),
        language=settings.language,
        beam_size=settings.beam_size,
        word_timestamps=False,
        vad_filter=True,  # Additional VAD filtering in Whisper
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
    )

    # Collect segments
    segments = []
    all_logprobs = []
    all_no_speech_probs = []
    full_text_parts = []

    for seg in segments_gen:
        segment_dict = {
            "id": seg.id,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "avg_logprob": seg.avg_logprob,
            "no_speech_prob": seg.no_speech_prob,
        }
        segments.append(segment_dict)
        full_text_parts.append(seg.text.strip())

        if seg.avg_logprob is not None:
            all_logprobs.append(seg.avg_logprob)
        if seg.no_speech_prob is not None:
            all_no_speech_probs.append(seg.no_speech_prob)

    full_text = " ".join(full_text_parts)

    # Calculate average metrics
    avg_logprob = sum(all_logprobs) / len(all_logprobs) if all_logprobs else None
    avg_no_speech_prob = sum(all_no_speech_probs) / len(all_no_speech_probs) if all_no_speech_probs else None

    logger.info(
        "Transcription completed",
        extra={
            "model": model_name,
            "segments_count": len(segments),
            "text_length": len(full_text),
            "avg_logprob": round(avg_logprob, 4) if avg_logprob else None,
            "detected_language": info.language,
        },
    )

    return TranscriptionResult(
        text=full_text,
        segments=segments,
        language=info.language,
        avg_logprob=avg_logprob,
        no_speech_prob=avg_no_speech_prob,
        model_name=model_name,
    )


def preload_models() -> None:
    """Preload both models into memory."""
    logger.info("Preloading Whisper models...")
    get_model_fast()
    get_model_accurate()
    logger.info("Whisper models loaded")
