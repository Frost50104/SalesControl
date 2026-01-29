"""Voice Activity Detection using webrtcvad."""

import io
import logging
from pathlib import Path

import numpy as np
import webrtcvad
from pydub import AudioSegment

from .settings import get_settings

logger = logging.getLogger(__name__)

# webrtcvad only supports 8000, 16000, 32000, 48000 Hz
# We'll use 16000 Hz as it's most efficient for speech
VAD_SAMPLE_RATE = 16000
VAD_SAMPLE_WIDTH = 2  # 16-bit audio


def load_audio_file(file_path: str) -> AudioSegment:
    """
    Load audio file and convert to format suitable for VAD.
    Handles various input formats (ogg/opus, mp3, wav, etc).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # Load with pydub (auto-detects format)
    audio = AudioSegment.from_file(file_path)

    # Convert to mono 16kHz 16-bit for VAD
    audio = audio.set_channels(1)
    audio = audio.set_frame_rate(VAD_SAMPLE_RATE)
    audio = audio.set_sample_width(VAD_SAMPLE_WIDTH)

    return audio


def audio_to_frames(
    audio: AudioSegment,
    frame_duration_ms: int = 30,
) -> list[tuple[int, bytes]]:
    """
    Split audio into frames for VAD processing.
    Returns list of (start_ms, frame_bytes) tuples.
    """
    frame_size = int(VAD_SAMPLE_RATE * frame_duration_ms / 1000) * VAD_SAMPLE_WIDTH
    raw_data = audio.raw_data

    frames = []
    offset = 0
    start_ms = 0

    while offset + frame_size <= len(raw_data):
        frame = raw_data[offset : offset + frame_size]
        frames.append((start_ms, frame))
        offset += frame_size
        start_ms += frame_duration_ms

    return frames


def detect_speech_frames(
    frames: list[tuple[int, bytes]],
    aggressiveness: int = 2,
) -> list[bool]:
    """
    Run VAD on frames and return list of speech/non-speech flags.

    Args:
        frames: List of (start_ms, frame_bytes) tuples
        aggressiveness: VAD aggressiveness (0-3), higher = more aggressive filtering

    Returns:
        List of booleans indicating speech (True) or silence (False)
    """
    vad = webrtcvad.Vad(aggressiveness)
    return [vad.is_speech(frame_data, VAD_SAMPLE_RATE) for _, frame_data in frames]


def frames_to_segments(
    frames: list[tuple[int, bytes]],
    speech_flags: list[bool],
    frame_duration_ms: int = 30,
    min_speech_ms: int = 100,
    min_silence_ms: int = 300,
) -> list[tuple[int, int]]:
    """
    Convert speech flags to speech segments with smoothing.

    Uses a simple state machine with hysteresis:
    - Requires min_speech_ms of continuous speech to start a segment
    - Requires min_silence_ms of continuous silence to end a segment

    Returns:
        List of (start_ms, end_ms) tuples for speech segments
    """
    if not frames or not speech_flags:
        return []

    min_speech_frames = max(1, min_speech_ms // frame_duration_ms)
    min_silence_frames = max(1, min_silence_ms // frame_duration_ms)

    segments = []
    in_speech = False
    speech_start_ms = 0
    consecutive_speech = 0
    consecutive_silence = 0

    for i, (start_ms, _) in enumerate(frames):
        is_speech = speech_flags[i]

        if not in_speech:
            if is_speech:
                consecutive_speech += 1
                if consecutive_speech >= min_speech_frames:
                    # Start new speech segment
                    in_speech = True
                    speech_start_ms = start_ms - (consecutive_speech - 1) * frame_duration_ms
                    consecutive_silence = 0
            else:
                consecutive_speech = 0
        else:
            if is_speech:
                consecutive_silence = 0
            else:
                consecutive_silence += 1
                if consecutive_silence >= min_silence_frames:
                    # End speech segment
                    end_ms = start_ms - (consecutive_silence - 1) * frame_duration_ms
                    if end_ms > speech_start_ms:
                        segments.append((speech_start_ms, end_ms))
                    in_speech = False
                    consecutive_speech = 0

    # Handle segment that extends to end of audio
    if in_speech:
        end_ms = frames[-1][0] + frame_duration_ms
        if end_ms > speech_start_ms:
            segments.append((speech_start_ms, end_ms))

    return segments


def run_vad(file_path: str) -> list[tuple[int, int]]:
    """
    Main VAD function: load audio and detect speech segments.

    Args:
        file_path: Path to audio file

    Returns:
        List of (start_ms, end_ms) tuples for speech segments
    """
    settings = get_settings()

    logger.debug(f"Loading audio file: {file_path}")
    audio = load_audio_file(file_path)

    logger.debug(f"Audio duration: {len(audio)}ms, converting to frames")
    frames = audio_to_frames(audio, settings.vad_frame_ms)

    logger.debug(f"Running VAD on {len(frames)} frames")
    speech_flags = detect_speech_frames(frames, settings.vad_aggressiveness)

    segments = frames_to_segments(frames, speech_flags, settings.vad_frame_ms)
    logger.debug(f"Found {len(segments)} speech segments")

    return segments
