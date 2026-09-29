"""Telephony audio conversion between phone codecs and the bridge format.

The bridge (and both upstream sessions) always speak base64 PCM16 mono 24 kHz,
so the browser, ACS, and Twilio paths feed all three upstream options identical audio
settings. Phone-side adapters convert at the edge:

- ACS bidirectional streaming is requested as ``pcm24KMono`` - no conversion.
- Twilio Media Streams carry G.711 mu-law 8 kHz - decode + upsample on the way
  in, low-pass + decimate + encode on the way out.

Each call owns its own converter instances because the resamplers keep a small
amount of state across chunks to avoid clicks at chunk boundaries.
"""

from __future__ import annotations

import base64

import numpy as np

_ULAW_BIAS = 0x84
_ULAW_CLIP = 32635


def _build_ulaw_decode_table() -> np.ndarray:
    table = np.zeros(256, dtype=np.int16)
    for code in range(256):
        value = ~code & 0xFF
        sign = value & 0x80
        exponent = (value >> 4) & 0x07
        mantissa = value & 0x0F
        sample = (((mantissa << 3) + _ULAW_BIAS) << exponent) - _ULAW_BIAS
        table[code] = -sample if sign else sample
    return table


_ULAW_DECODE = _build_ulaw_decode_table()


def ulaw_decode(data: bytes) -> np.ndarray:
    """Decode G.711 mu-law bytes to int16 PCM samples."""

    return _ULAW_DECODE[np.frombuffer(data, dtype=np.uint8)]


def ulaw_encode(samples: np.ndarray) -> bytes:
    """Encode int16 PCM samples to G.711 mu-law bytes."""

    x = samples.astype(np.int32)
    sign = (x < 0).astype(np.int32)
    magnitude = np.minimum(np.abs(x), _ULAW_CLIP) + _ULAW_BIAS
    exponent = np.clip(np.floor(np.log2(magnitude)).astype(np.int32) - 7, 0, 7)
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    encoded = ~((sign << 7) | (exponent << 4) | mantissa) & 0xFF
    return encoded.astype(np.uint8).tobytes()


def _lowpass_taps(num_taps: int, cutoff_hz: float, rate_hz: int) -> np.ndarray:
    n = np.arange(num_taps) - (num_taps - 1) / 2
    fc = cutoff_hz / rate_hz
    taps = 2 * fc * np.sinc(2 * fc * n) * np.hamming(num_taps)
    return (taps / taps.sum()).astype(np.float32)


class Upsampler3x:
    """8 kHz -> 24 kHz linear interpolation that carries the last sample across chunks."""

    def __init__(self) -> None:
        self._previous = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return np.zeros(0, dtype=np.int16)
        current = samples.astype(np.float32)
        previous = np.concatenate(([self._previous], current[:-1])).astype(np.float32)
        delta = current - previous
        out = np.empty(current.size * 3, dtype=np.float32)
        out[0::3] = previous
        out[1::3] = previous + delta / 3
        out[2::3] = previous + 2 * delta / 3
        self._previous = float(current[-1])
        return np.clip(np.round(out), -32768, 32767).astype(np.int16)


class Downsampler3x:
    """24 kHz -> 8 kHz anti-aliased decimation that keeps filter history and phase."""

    NUM_TAPS = 31

    def __init__(self) -> None:
        self._taps = _lowpass_taps(self.NUM_TAPS, cutoff_hz=3400, rate_hz=24000)
        self._history = np.zeros(self.NUM_TAPS - 1, dtype=np.float32)
        self._phase = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return np.zeros(0, dtype=np.int16)
        buffer = np.concatenate((self._history, samples.astype(np.float32)))
        filtered = np.convolve(buffer, self._taps, mode="valid")
        out = filtered[self._phase :: 3]
        self._phase = (self._phase - filtered.size) % 3
        self._history = buffer[-(self.NUM_TAPS - 1) :]
        return np.clip(np.round(out), -32768, 32767).astype(np.int16)


def pcm16_b64_to_array(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    if len(raw) % 2:
        raw = raw[:-1]
    return np.frombuffer(raw, dtype="<i2")


def array_to_pcm16_b64(samples: np.ndarray) -> str:
    return base64.b64encode(samples.astype("<i2").tobytes()).decode("ascii")


class MulawTelephonyCodec:
    """Per-call converter between Twilio mu-law 8 kHz and bridge PCM16 24 kHz."""

    def __init__(self) -> None:
        self._up = Upsampler3x()
        self._down = Downsampler3x()

    def inbound(self, mulaw_b64: str) -> str:
        """Phone -> bridge: base64 mu-law 8 kHz to base64 PCM16 24 kHz."""

        pcm_8k = ulaw_decode(base64.b64decode(mulaw_b64))
        return array_to_pcm16_b64(self._up.process(pcm_8k))

    def outbound(self, pcm24k_b64: str) -> str:
        """Bridge -> phone: base64 PCM16 24 kHz to base64 mu-law 8 kHz."""

        pcm_8k = self._down.process(pcm16_b64_to_array(pcm24k_b64))
        return base64.b64encode(ulaw_encode(pcm_8k)).decode("ascii")
