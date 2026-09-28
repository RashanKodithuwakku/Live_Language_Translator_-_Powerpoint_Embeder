"""
Server-side speech gate (E1).

Uses webrtcvad when available (good on constant mixer noise floors), with an
energy-margin fallback so the gate still works if the wheel is missing.

Keeps a pre-roll ring buffer and hangover so word onsets/ends are not clipped.
Sits UPSTREAM of STT fan-out: all recognisers open/close together.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

import config

log = logging.getLogger("vad")

try:
    import webrtcvad

    _HAS_WEBRTC = True
except ImportError:
    webrtcvad = None  # type: ignore
    _HAS_WEBRTC = False
    log.warning("webrtcvad not installed — using energy VAD only")


@dataclass
class GateDecision:
    speech_active: bool          # currently in a speech segment (incl hangover)
    just_started: bool           # rising edge — flush pre-roll then open streams
    just_ended: bool             # falling edge — close streams after hangover
    preroll: list[bytes]         # chunks to send first on just_started
    frame_is_speech: bool


class SpeechGate:
    def __init__(self) -> None:
        self._aggressiveness = max(0, min(3, config.VAD_AGGRESSIVENESS))
        self._vad = webrtcvad.Vad(self._aggressiveness) if _HAS_WEBRTC else None
        self._preroll_n = max(1, int(config.VAD_PREROLL_MS / 100))
        self._hangover_n = max(1, int(config.VAD_HANGOVER_MS / 100))
        self._min_speech_n = max(1, int(config.VAD_MIN_SPEECH_MS / 100))
        self._ring: deque[bytes] = deque(maxlen=self._preroll_n)
        self._active = False
        self._speech_run = 0
        self._silence_run = 0
        self._noise_floor = -70.0
        self._energy_boost = 0.0  # raised by noise-burn guard

    def bump_threshold(self) -> None:
        self._energy_boost = min(18.0, self._energy_boost + 3.0)
        log.warning("VAD threshold raised (+%.0f dB total boost)", self._energy_boost)

    def reset_boost(self) -> None:
        self._energy_boost = 0.0

    def _energy_speech(self, pcm: bytes) -> bool:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return False
        rms = float(np.sqrt(np.mean(samples * samples)))
        level = 20 * np.log10(rms / 32768.0) if rms > 0 else -120.0
        # Slow-rising noise floor: adapts quickly downward, slowly upward so
        # continuous speech does not redefine itself as "noise".
        if level < self._noise_floor + 3.0:
            self._noise_floor = 0.90 * self._noise_floor + 0.10 * level
        else:
            self._noise_floor = 0.998 * self._noise_floor + 0.002 * level
        threshold = max(self._noise_floor + 12.0 + self._energy_boost, -55.0 + self._energy_boost)
        return level > threshold

    def _webrtc_speech(self, pcm: bytes) -> bool:
        # webrtcvad wants 10/20/30 ms frames at 8/16/32/48 kHz.
        if not self._vad or len(pcm) < 320:
            return self._energy_speech(pcm)
        votes = 0
        frames = 0
        # 20 ms = 640 bytes at 16 kHz mono int16
        step = 640
        for i in range(0, len(pcm) - step + 1, step):
            frames += 1
            try:
                if self._vad.is_speech(pcm[i:i + step], config.SAMPLE_RATE_HZ):
                    votes += 1
            except Exception:
                return self._energy_speech(pcm)
        if frames == 0:
            return self._energy_speech(pcm)
        # webrtcvad alone is enough; energy is only the fallback path.
        return votes * 2 >= frames

    def process(self, pcm: bytes) -> GateDecision:
        if not config.VAD_ENABLED:
            return GateDecision(True, False, False, [], True)

        is_speech = self._webrtc_speech(pcm) if self._vad else self._energy_speech(pcm)
        self._ring.append(pcm)
        just_started = False
        just_ended = False
        preroll: list[bytes] = []

        if is_speech:
            self._speech_run += 1
            self._silence_run = 0
        else:
            self._silence_run += 1
            self._speech_run = 0

        if not self._active:
            if self._speech_run >= self._min_speech_n:
                self._active = True
                just_started = True
                preroll = list(self._ring)
                self._ring.clear()
        else:
            if self._silence_run >= self._hangover_n:
                self._active = False
                just_ended = True
                self._silence_run = 0

        return GateDecision(
            speech_active=self._active,
            just_started=just_started,
            just_ended=just_ended,
            preroll=preroll,
            frame_is_speech=is_speech,
        )
