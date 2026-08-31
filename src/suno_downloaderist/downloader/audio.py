"""Audio format conversion utilities for Suno Song Downloaderist.

Provides pure-Python/C-extension WAV to MP3 encoding using lameenc
without requiring external ffmpeg installation.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import lameenc
    LAMEENC_AVAILABLE = True
except ImportError:
    LAMEENC_AVAILABLE = False


def convert_wav_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    bitrate_kbps: int = 320,
    quality: int = 2,
) -> bool:
    """Convert an uncompressed PCM WAV file to high-bitrate MP3.

    Args:
        wav_path: Path to source .wav file.
        mp3_path: Path to destination .mp3 file.
        bitrate_kbps: MP3 bitrate in kbps (default: 320 for master quality).
        quality: LAME quality preset (0=highest/slowest, 2=near-best/fast, 9=lowest).

    Returns:
        bool: True if conversion succeeded, False otherwise.
    """
    if not LAMEENC_AVAILABLE:
        logger.error("lameenc is not installed. Cannot convert WAV to MP3.")
        return False

    if not wav_path.exists():
        logger.error("Source WAV file not found: %s", wav_path)
        return False

    try:
        with wave.open(str(wav_path), "rb") as w:
            n_channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()
            n_frames = w.getnframes()
            pcm_data = w.readframes(n_frames)

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(bitrate_kbps)
        encoder.set_in_sample_rate(framerate)
        encoder.set_channels(n_channels)
        encoder.set_quality(quality)
        
        mp3_data = encoder.encode(pcm_data) + encoder.flush()

        mp3_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path.write_bytes(mp3_data)
        logger.debug("Converted WAV to MP3: %s (%d bytes)", mp3_path.name, len(mp3_data))
        return True

    except Exception as exc:
        logger.error("Failed to convert %s to MP3: %s", wav_path.name, exc)
        return False
