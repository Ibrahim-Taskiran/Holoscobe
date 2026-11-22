"""Helpers for the audio tests: pitch/spectrum estimators and a fake sounddevice backend."""
from __future__ import annotations

from typing import Callable

import numpy as np

SR = 48000


def fundamental_hz(x: np.ndarray, sr: int, expected: float, skip_s: float = 0.1) -> float:
    """Strongest spectral peak within half an octave of `expected`, parabolic interpolation (log mag)."""
    x = np.asarray(x, dtype=np.float64)[int(skip_s * sr):]
    x = x * np.hanning(len(x))
    n = 1 << 20
    mag = np.abs(np.fft.rfft(x, n))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    lo, hi = np.searchsorted(freqs, [expected / 2 ** 0.5, expected * 2 ** 0.5])
    k = lo + int(np.argmax(mag[lo:hi]))
    a, b, c = np.log(mag[k - 1:k + 2] + 1e-30)
    p = 0.5 * (a - c) / (a - 2 * b + c)
    return (k + p) * sr / n


def spectral_centroid(x: np.ndarray, sr: int) -> float:
    mag = np.abs(np.fft.rfft(np.asarray(x, dtype=np.float64) * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    return float((mag * freqs).sum() / max(mag.sum(), 1e-30))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def render_blocks(synth, total: int, block: int = 256) -> np.ndarray:
    out = np.zeros(total, dtype=np.float32)
    pos = 0
    while pos < total:
        k = min(block, total - pos)
        synth.render(k, out=out[pos:pos + k])
        pos += k
    return out


# ---------- fake sounddevice ----------

class FakePortAudioError(Exception):
    pass


class FakeFlags:
    def __init__(self, output_underflow: bool = False) -> None:
        self.output_underflow = output_underflow


class FakeWasapiSettings:
    def __init__(self, exclusive: bool = False, auto_convert: bool = False, explicit_sample_format: bool = False):
        self.exclusive = exclusive
        self.auto_convert = auto_convert


class FakeStream:
    def __init__(self, backend: "FakeBackend", **kw) -> None:
        self.kw = kw
        self.backend = backend
        backend.attempts.append(kw)
        if backend.fail(kw):
            raise FakePortAudioError(f"Invalid device {kw['device']} @ {kw['samplerate']}")
        self.latency = backend.stream_latency
        self.active = False
        self.closed = False
        self.stopped = 0
        backend.opened.append(self)

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.stopped += 1
        if self.active:
            self.active = False
            self.kw["finished_callback"]()

    abort = stop

    def close(self) -> None:
        self.closed = True
        self.active = False

    def drive(self, frames: int | None = None, status=None) -> np.ndarray:
        frames = frames or self.kw["blocksize"]
        out = np.full((frames, self.kw["channels"]), 9.0, dtype=np.float32)
        self.kw["callback"](out, frames, None, status if status is not None else FakeFlags())
        return out

    def die(self) -> None:
        """Simulate a device loss: PortAudio ends the stream on its own."""
        self.active = False
        self.kw["finished_callback"]()


# hostapi index -> name; device list: (name, hostapi, max_out, default_sr)
HOSTAPIS = ["MME", "Windows DirectSound", "Windows WASAPI", "Windows WDM-KS"]
DEVICES = [
    ("Microsoft Ses Eşleyicisi - Output", 0, 2, 44100.0),     # 0
    ("Kulaklık (Soundcore Life Q30", 0, 2, 44100.0),           # 1 (MME truncation)
    ("Mikrofon (USB)", 0, 0, 44100.0),                          # 2 input only
    ("Birincil Ses Sürücüsü", 1, 2, 44100.0),                  # 3
    ("Kulaklık (Soundcore Life Q30)", 1, 2, 44100.0),           # 4
    ("Hoparlör (Realtek(R) Audio)", 2, 2, 48000.0),             # 5 WASAPI default
    ("Kulaklık (Soundcore Life Q30)", 2, 2, 48000.0),           # 6
    ("Hoparlör (Realtek HD)", 3, 2, 48000.0),                   # 7 WDM-KS
]
DEFAULTS = {0: 0, 1: 3, 2: 5, 3: 7}


class FakeBackend:
    PortAudioError = FakePortAudioError
    WasapiSettings = FakeWasapiSettings
    CallbackFlags = FakeFlags

    def __init__(self, fail: Callable[[dict], bool] | None = None, devices=None, defaults=None,
                 stream_latency: float = 0.010) -> None:
        self.devices = list(devices if devices is not None else DEVICES)
        self.defaults = dict(defaults if defaults is not None else DEFAULTS)
        self.fail = fail or (lambda kw: False)
        self.attempts: list[dict] = []
        self.opened: list[FakeStream] = []
        self.stream_latency = stream_latency

    def hostapi_of(self, index: int) -> str:
        return HOSTAPIS[self.devices[index][1]]

    def query_hostapis(self):
        return tuple({"name": n, "devices": [i for i, d in enumerate(self.devices) if d[1] == hi],
                      "default_output_device": self.defaults.get(hi, -1)} for hi, n in enumerate(HOSTAPIS))

    def query_devices(self):
        return [{"name": d[0], "index": i, "hostapi": d[1], "max_input_channels": 0 if d[2] else 2,
                 "max_output_channels": d[2], "default_samplerate": d[3]} for i, d in enumerate(self.devices)]

    def OutputStream(self, **kw) -> FakeStream:  # noqa: N802 - sounddevice API name
        return FakeStream(self, **kw)

    @property
    def stream(self) -> FakeStream:
        return self.opened[-1]
