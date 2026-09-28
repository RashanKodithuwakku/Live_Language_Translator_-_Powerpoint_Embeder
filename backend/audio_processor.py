"""
Streaming audio cleanup (A5).

Default: 80 Hz high-pass + gentle peak normalisation.
Spectral denoise (noisereduce) is OFF unless NOISE_REDUCTION_STRENGTH > 0.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from scipy.signal import butter, sosfilt

import config

try:
    import noisereduce as nr
except ImportError:
    nr = None

SAMPLE_RATE = config.SAMPLE_RATE_HZ
HIGHPASS_HZ = 80
N_FFT = 512
HISTORY_SECONDS = 8.0
NOISE_PERCENTILE = 20

_HPF_SOS = butter(4, HIGHPASS_HZ, btype="highpass", fs=SAMPLE_RATE, output="sos")


class AudioProcessor:
    def __init__(self, strength: float | None = None) -> None:
        self._strength = max(0.0, min(1.0, config.NOISE_REDUCTION_STRENGTH if strength is None else strength))
        self._gate_enabled = nr is not None and self._strength > 0.0
        self._normalize = config.ENABLE_NORMALIZE
        self._zi = np.zeros((_HPF_SOS.shape[0], 2))
        self._context = np.zeros(2 * N_FFT, dtype=np.float32)
        self._history: deque[tuple[float, np.ndarray]] = deque()
        self._history_samples = 0
        self._target_peak = 0.25  # ~-12 dBFS

    def process(self, pcm: bytes) -> bytes:
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if x.size == 0:
            return pcm

        x, self._zi = sosfilt(_HPF_SOS, x, zi=self._zi)
        x = x.astype(np.float32)

        if self._gate_enabled:
            x = self._denoise(x)

        if self._normalize:
            peak = float(np.max(np.abs(x))) if x.size else 0.0
            if peak > 1e-4:
                # Gentle: never amplify more than 4×, never above 0.9
                gain = min(4.0, self._target_peak / peak)
                if peak * gain > 0.9:
                    gain = 0.9 / peak
                # Only boost quiet speech; leave loud alone
                if gain > 1.0:
                    x = x * gain

        y = np.clip(x * 32768.0, -32768, 32767).astype(np.int16)
        return y.tobytes()

    def _denoise(self, x: np.ndarray) -> np.ndarray:
        energy = float(np.mean(x * x))
        self._history.append((energy, x.copy()))
        self._history_samples += x.size
        while self._history and self._history_samples > int(HISTORY_SECONDS * SAMPLE_RATE):
            e, old = self._history.popleft()
            self._history_samples -= old.size

        if self._history_samples < SAMPLE_RATE:
            return x

        energies = np.array([e for e, _ in self._history])
        cutoff = np.percentile(energies, NOISE_PERCENTILE)
        noise_chunks = [c for e, c in self._history if e <= cutoff]
        if not noise_chunks:
            return x
        y_noise = np.concatenate(noise_chunks)
        ctx = np.concatenate([self._context, x])
        reduced = nr.reduce_noise(
            y=ctx,
            sr=SAMPLE_RATE,
            y_noise=y_noise,
            stationary=True,
            prop_decrease=self._strength,
            n_fft=N_FFT,
            freq_mask_smooth_hz=None,
            time_mask_smooth_ms=50,
        )
        out = reduced[-x.size:]
        self._context = ctx[-2 * N_FFT:]
        return out.astype(np.float32)
