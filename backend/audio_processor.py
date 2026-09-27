"""
audio_processor.py
──────────────────
Handles all raw audio preprocessing before the bytes are forwarded
to Google Cloud Speech-to-Text.

Pipeline:
  1. Receive raw PCM int16 bytes from the browser (LINEAR16, 16 kHz, mono)
  2. Convert to float32 numpy array (noisereduce expects floats)
  3. Run noisereduce's stationary spectral-gate noise-reduction pass
     (noisereduce is a real, pip-installable library:
      https://github.com/timsainburg/noisereduce)
  4. Convert back to int16 PCM bytes and return

Why noisereduce?
  - Stationary mode works well against constant-background-noise sources
    common at events (HVAC, projector fans, crowd hum).
  - Non-blocking: the entire call is synchronous and fast enough to run
    inline in the async handler for chunk sizes <= 4096 samples.
  - Alternative considered: pyaudioanalysis – significantly heavier;
    not worth the dependency weight for a stationary noise profile.

SAMPLE_RATE and SAMPLE_WIDTH must match what getUserMedia is configured
to request in the frontend's useAudioStream hook.
"""

import os
import numpy as np

try:
    import noisereduce as nr
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    NOISEREDUCE_AVAILABLE = False

# ── Constants ────────────────────────────────────────────────────────────────
SAMPLE_RATE: int = 16_000   # Hz  – must match frontend getUserMedia constraint
SAMPLE_WIDTH: int = 2       # bytes per sample (int16)
CHANNELS: int = 1           # mono

# Read noise-reduction strength from env (0.0 = off, 1.0 = full)
_NR_STRENGTH = float(os.getenv("NOISE_REDUCTION_STRENGTH", "0.5"))


def pcm_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert raw int16 PCM bytes → float32 array in [-1.0, 1.0]."""
    int16_array = np.frombuffer(pcm_bytes, dtype=np.int16)
    return int16_array.astype(np.float32) / 32768.0


def float32_to_pcm_bytes(float_array: np.ndarray) -> bytes:
    """Convert float32 array in [-1.0, 1.0] → raw int16 PCM bytes."""
    clipped = np.clip(float_array, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


def process_audio_chunk(pcm_bytes: bytes) -> bytes:
    """
    Apply spectral-gate noise reduction to one chunk of PCM audio.

    If noisereduce is unavailable or strength is 0, the bytes are
    returned unchanged so the rest of the pipeline continues normally.

    Args:
        pcm_bytes: Raw LINEAR16 PCM bytes from the browser.

    Returns:
        Processed PCM bytes, same format, ready for Google STT.
    """
    if not NOISEREDUCE_AVAILABLE or _NR_STRENGTH == 0.0:
        return pcm_bytes

    audio_float = pcm_bytes_to_float32(pcm_bytes)

    # noisereduce stationary mode:
    #   - stationary=True → assumes a constant noise profile (good for venue hum)
    #   - prop_decrease controls how aggressively noise is attenuated
    reduced = nr.reduce_noise(
        y=audio_float,
        sr=SAMPLE_RATE,
        stationary=True,
        prop_decrease=_NR_STRENGTH,
    )

    return float32_to_pcm_bytes(reduced)
