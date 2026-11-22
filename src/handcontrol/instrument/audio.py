"""Audio output for instrument mode: a low-latency PortAudio stream (via sounddevice) driving GuitarSynth.

Thread model:
- Any thread calls push()/set_volume()/set_tone(); push is a lock-free deque append.
- The PortAudio callback thread pops the events, lets the synth handle them and renders the block. It never
  blocks, logs or takes locks; an exception there outputs silence and is remembered.
- A small watchdog thread (and stats()) report remembered errors through on_error, never from the callback.
- start()/stop()/play_test_tone() are called from the app (GUI/control) thread.

sounddevice is imported lazily, so importing this module never fails when it is missing.
"""
from __future__ import annotations

import collections
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from .events import AllOff, NoteOn
from .synth import GuitarSynth

HOSTAPI_ORDER: tuple[str, ...] = ("Windows WASAPI", "Windows DirectSound", "MME")
BLOCKSIZES = {"low": 128, "normal": 256}
MAX_QUEUE = 512
MAX_EVENTS_PER_CALLBACK = 256
STOP_FADE_MS = 15.0
TEST_TONE_S = 1.5
WATCHDOG_INTERVAL_S = 0.2


def _load_backend(backend: Any) -> Any:
    if backend is not None:
        return backend
    import sounddevice  # lazy: optional at import time

    return sounddevice


@dataclass(frozen=True)
class OutputDevice:
    index: int
    name: str
    hostapi: str
    default: bool


def _hostapis(backend: Any) -> list[dict]:
    return [dict(h) for h in backend.query_hostapis()]


def _devices(backend: Any) -> list[dict]:
    return [dict(d) for d in backend.query_devices()]


def list_output_devices(backend=None) -> list[OutputDevice]:
    """Output devices with unique names (preferred host APIs first). Never raises."""
    try:
        backend = _load_backend(backend)
        apis = _hostapis(backend)
        devs = _devices(backend)
        names = [str(h.get("name", "")) for h in apis]
        order = [i for n in HOSTAPI_ORDER for i, a in enumerate(names) if a == n]
        if not order:
            order = list(range(len(apis)))
        result: list[OutputDevice] = []
        seen: set[str] = set()
        for ai in order:
            default_idx = apis[ai].get("default_output_device", -1)
            for idx in apis[ai].get("devices", []):
                if not (0 <= idx < len(devs)):
                    continue
                d = devs[idx]
                if int(d.get("max_output_channels", 0)) <= 0:
                    continue
                name = str(d.get("name", "")).strip()
                if not name or name in seen or any(s.startswith(name) for s in seen):
                    continue        # MME truncates names to 31 chars: skip the truncated duplicate
                seen.add(name)
                result.append(OutputDevice(int(idx), name, names[ai], idx == default_idx))
        return result
    except Exception:
        return []


@dataclass(frozen=True)
class AudioStats:
    running: bool
    hostapi: str
    device: str
    sample_rate: int
    blocksize: int
    output_latency_ms: float
    callbacks: int
    callback_ms_mean: float
    callback_ms_max: float
    load_max: float
    underflows: int
    event_latency_ms_mean: float
    event_latency_ms_last: float


def _match_device(devs: list[dict], indices: list[int], wanted: str) -> Optional[int]:
    wanted = wanted.strip()
    if not wanted:
        return None
    outs = [i for i in indices if 0 <= i < len(devs) and int(devs[i].get("max_output_channels", 0)) > 0]
    for i in outs:
        if str(devs[i].get("name", "")).strip() == wanted:
            return i
    for i in outs:            # truncated names (MME) in either direction
        n = str(devs[i].get("name", "")).strip()
        if n and (wanted.startswith(n) or n.startswith(wanted)):
            return i
    return None


class AudioOutput:
    def __init__(self, synth: GuitarSynth | None = None, *, backend=None, device: str = "", latency: str = "low",
                 sample_rate: int = 48000, on_error: Callable[[str], None] | None = None,
                 clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000.0,
                 perf_clock: Callable[[], float] = time.perf_counter,
                 stall_timeout_s: float | None = 3.0) -> None:
        self._synth = synth if synth is not None else GuitarSynth(sample_rate=sample_rate)
        self._backend_arg = backend
        self.device = device or ""
        self.latency = latency if latency in BLOCKSIZES else "low"
        self.sample_rate = int(sample_rate)
        self._on_error = on_error
        self._clock_ms = clock_ms
        self._perf = perf_clock
        self._stall_timeout = stall_timeout_s
        self._queue: collections.deque = collections.deque()
        self._overflow_alloff: Optional[AllOff] = None
        self._buf = np.zeros(8192, dtype=np.float32)
        self._stream: Any = None
        self._running = False
        self._stopping = False
        self._temp = False
        self._lock = threading.RLock()   # app side only, never in the callback; re-entrant: on_error may call stop()
        self._watchdog: Optional[threading.Thread] = None
        self._wd_stop = threading.Event()
        self._reset_info()
        self._reset_counters()

    # ---------- public ----------

    @property
    def synth(self) -> GuitarSynth:
        return self._synth

    @property
    def running(self) -> bool:
        return self._running

    def push(self, event) -> None:
        q = self._queue
        q.append(event)
        if len(q) > MAX_QUEUE:                 # consumer is stalled: drop the oldest event
            try:
                old = q.popleft()
            except IndexError:
                return
            if type(old) is AllOff:            # it was older than everything left: apply it first
                self._overflow_alloff = old

    def set_volume(self, v: float) -> None:
        self._synth.set_volume(v)              # single attribute assignment: thread-safe

    def set_tone(self, t: str) -> None:
        self._synth.set_tone(t)

    def start(self) -> bool:
        with self._lock:
            if self._running:
                self._temp = False             # the app adopts a test-tone stream
                return True
            return self._open(temporary=False)

    def stop(self) -> None:
        with self._lock:
            self._close()

    def stats(self) -> AudioStats:
        self._check_errors()
        n = self._callbacks
        return AudioStats(
            running=self._running, hostapi=self._hostapi_name, device=self._device_name,
            sample_rate=self._sr, blocksize=self._blocksize, output_latency_ms=self._out_lat_ms,
            callbacks=n, callback_ms_mean=(self._cb_sum / n * 1000.0) if n else 0.0,
            callback_ms_max=self._cb_max * 1000.0, load_max=self._load_max, underflows=self._underflows,
            event_latency_ms_mean=(self._lat_sum / self._lat_n) if self._lat_n else 0.0,
            event_latency_ms_last=self._lat_last,
        )

    def play_test_tone(self) -> bool:
        """A short E-major arpeggio. Opens a temporary ~1.5 s stream when the output is not running."""
        with self._lock:
            if not self._running:
                if not self._open(temporary=True):
                    return False
                stream = self._stream
                timer = threading.Timer(TEST_TONE_S, self._close_temp, args=(stream,))
                timer.daemon = True
                timer.start()
        for i, (midi, vel) in enumerate(((52, 0.75), (56, 0.7), (59, 0.7), (64, 0.8))):
            self.push(NoteOn(string=i, midi=float(midi), velocity=vel, note_id=-1 - i, t_ms=math.nan,
                             delay_ms=110.0 * i))
        return True

    # ---------- stream management (app thread, under self._lock) ----------

    def _reset_info(self) -> None:
        self._hostapi_name = ""
        self._device_name = ""
        self._sr = 0
        self._blocksize = 0
        self._channels = 0
        self._out_lat_ms = 0.0

    def _reset_counters(self) -> None:
        self._callbacks = 0
        self._cb_sum = 0.0
        self._cb_max = 0.0
        self._load_max = 0.0
        self._underflows = 0
        self._lat_sum = 0.0
        self._lat_n = 0
        self._lat_last = 0.0
        self._cb_error: Optional[BaseException] = None
        self._died = False
        self._error_reported = False
        self._last_cb = 0.0

    def _report(self, text: str) -> None:
        cb = self._on_error
        if cb is None:
            return
        try:
            cb(text)
        except Exception:
            pass

    def _candidates(self, backend: Any) -> list[tuple[str, int, dict]]:
        apis = _hostapis(backend)
        devs = _devices(backend)
        out: list[tuple[str, int, dict]] = []
        for name in HOSTAPI_ORDER:
            for a in apis:
                if str(a.get("name", "")) != name:
                    continue
                indices = [int(i) for i in a.get("devices", [])]
                idx = _match_device(devs, indices, self.device)
                if idx is None:
                    idx = int(a.get("default_output_device", -1))
                    if not (0 <= idx < len(devs)) or int(devs[idx].get("max_output_channels", 0)) <= 0:
                        idx = next((i for i in indices if 0 <= i < len(devs)
                                    and int(devs[i].get("max_output_channels", 0)) > 0), -1)
                if idx >= 0:
                    out.append((name, idx, devs[idx]))
        return out

    def _open(self, temporary: bool) -> bool:
        try:
            backend = _load_backend(self._backend_arg)
        except Exception as exc:
            self._report(f"Ses kütüphanesi yüklenemedi: {exc}")
            return False
        try:
            candidates = self._candidates(backend)
        except Exception as exc:
            self._report(f"Ses cihazları okunamadı: {exc}")
            return False
        if not candidates:
            self._report("Ses çıkış cihazı bulunamadı.")
            return False
        blocksize = BLOCKSIZES[self.latency]
        last_err = ""
        for api_name, idx, dev in candidates:
            extra = None
            if api_name == "Windows WASAPI" and hasattr(backend, "WasapiSettings"):
                try:
                    extra = backend.WasapiSettings(auto_convert=True)
                except Exception:
                    extra = None
            rates = [self.sample_rate]
            dsr = int(round(float(dev.get("default_samplerate", 0) or 0)))
            if dsr > 0 and dsr != self.sample_rate:
                rates.append(dsr)
            maxch = int(dev.get("max_output_channels", 1))
            chans = [2, 1] if maxch >= 2 else [1]
            for sr in rates:
                for ch in chans:
                    stream = None
                    try:
                        if sr != self._synth.sample_rate:
                            synth = self._synth.with_sample_rate(sr)
                        else:
                            synth = self._synth
                        kw = dict(device=idx, samplerate=sr, blocksize=blocksize, channels=ch, dtype="float32",
                                  latency="low", callback=self._callback, finished_callback=self._finished)
                        if extra is not None:
                            kw["extra_settings"] = extra
                        self._reset_counters()
                        self._synth = synth
                        self._channels = ch
                        self._sr = sr
                        self._last_cb = self._perf()
                        self._stopping = False
                        stream = backend.OutputStream(**kw)
                        stream.start()
                    except Exception as exc:   # PortAudioError and anything a driver raises
                        last_err = str(exc) or type(exc).__name__
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception:
                                pass
                        continue
                    self._stream = stream
                    self._hostapi_name = api_name
                    self._device_name = str(dev.get("name", ""))
                    self._blocksize = blocksize
                    try:
                        lat = stream.latency
                        lat = float(lat[1] if isinstance(lat, (tuple, list)) else lat)
                    except Exception:
                        lat = 0.0
                    self._out_lat_ms = lat * 1000.0 if math.isfinite(lat) else 0.0
                    self._running = True
                    self._temp = temporary
                    self._start_watchdog()
                    return True
        self._reset_info()
        self._report(f"Ses çıkışı açılamadı: {last_err}" if last_err else "Ses çıkışı açılamadı.")
        return False

    def _close(self) -> None:
        stream = self._stream
        self._stopping = True
        self._wd_stop.set()
        wd = self._watchdog
        if wd is not None and wd is not threading.current_thread():
            wd.join(timeout=1.0)
        self._watchdog = None
        if stream is None:
            self._running = False
            self._temp = False
            return
        try:
            if self._running and not self._died and self._cb_error is None:
                self.push(AllOff(fade_ms=STOP_FADE_MS, t_ms=self._clock_ms()))
                time.sleep((STOP_FADE_MS + 2.0 * 1000.0 * self._blocksize / max(1, self._sr)) / 1000.0)
                stream.stop()
            else:
                (getattr(stream, "abort", None) or stream.stop)()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        self._stream = None
        self._running = False
        self._temp = False
        self._queue.clear()

    def _close_temp(self, stream: Any) -> None:
        with self._lock:
            if self._temp and self._stream is stream:
                self._close()

    # ---------- errors ----------

    def _start_watchdog(self) -> None:
        self._wd_stop = threading.Event()
        stop_ev = self._wd_stop

        def loop() -> None:
            while not stop_ev.wait(WATCHDOG_INTERVAL_S):
                self._check_errors()

        t = threading.Thread(target=loop, name="audio-watchdog", daemon=True)
        self._watchdog = t
        t.start()

    def _check_errors(self) -> None:
        if not self._running or self._stopping or self._error_reported:
            return
        text = ""
        if self._died:
            text = "Ses cihazı hatası: ses akışı beklenmedik şekilde durdu (cihaz çıkarılmış olabilir)."
        elif self._cb_error is not None:
            text = f"Ses cihazı hatası: {self._cb_error}"
        elif self._stall_timeout is not None and self._perf() - self._last_cb > self._stall_timeout:
            text = "Ses cihazı hatası: ses cihazı yanıt vermiyor."
        if not text:
            return
        if not self._lock.acquire(timeout=0.05):   # start/stop in progress: try again next round
            return
        try:
            if self._error_reported or not self._running or self._stopping:
                return
            self._error_reported = True
            self._running = False
            self._died = True
            stream = self._stream
            self._stream = None
        finally:
            self._lock.release()
        self._wd_stop.set()
        if stream is not None:
            try:
                (getattr(stream, "abort", None) or stream.stop)()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._report(text)

    def _finished(self) -> None:          # PortAudio thread, when the stream ends
        if not self._stopping:
            self._died = True

    # ---------- audio callback (PortAudio thread) ----------

    def _callback(self, outdata, frames, time_info, status) -> None:
        perf = self._perf
        t0 = perf()
        try:
            if status is not None and getattr(status, "output_underflow", False):
                self._underflows += 1
            synth = self._synth
            ao = self._overflow_alloff
            if ao is not None:
                self._overflow_alloff = None
                synth.handle(ao)
            q = self._queue
            now = None
            for _ in range(MAX_EVENTS_PER_CALLBACK):
                try:
                    ev = q.popleft()
                except IndexError:
                    break
                if type(ev) is NoteOn:
                    if now is None:
                        now = self._clock_ms()
                    lat = now - ev.t_ms + self._out_lat_ms
                    if lat == lat:             # skip NaN (test tone)
                        self._lat_sum += lat
                        self._lat_n += 1
                        self._lat_last = lat
                synth.handle(ev)
            buf = self._buf
            n = min(frames, buf.shape[0])
            mb = synth.max_block
            pos = 0
            while pos < n:
                k = min(mb, n - pos)
                synth.render(k, out=buf[pos: pos + k])
                pos += k
            if n < frames:
                outdata.fill(0)
            col = buf[:n, None]
            outdata[:n] = col                  # broadcasts mono to every channel
        except Exception as exc:
            try:
                outdata.fill(0)
            except Exception:
                pass
            if self._cb_error is None:
                self._cb_error = exc
        t1 = perf()
        dt = t1 - t0
        self._last_cb = t1
        self._callbacks += 1
        self._cb_sum += dt
        if dt > self._cb_max:
            self._cb_max = dt
        sr = self._sr or self._synth.sample_rate
        if frames > 0:
            load = dt * sr / frames
            if load > self._load_max:
                self._load_max = load


__all__ = ["AudioOutput", "AudioStats", "OutputDevice", "list_output_devices"]
