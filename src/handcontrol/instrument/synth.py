"""Real-time plucked-string synthesizer: extended Karplus-Strong (Jaffe & Smith), vectorized with numpy.

Signal flow per voice (one voice = one vibrating string):

    excitation (colored noise burst written into the delay line at the pluck)
        -> loop:  y[n] = g * (c0' y[n-M] + c1' y[n-M-1] + c2' y[n-M-2])
                  = g * loss(z) * interp(z) * z^-M applied to y
           loss(z)   = (1-S) + S z^-1         weighted two-point loss/brightness filter (damping)
           interp(z) = (1-a) + a z^-1         linear-interpolation fractional delay (tuning + bend)
           g         = per-period gain giving a note-dependent T60 (low notes ring longer)

The loop filter is FIR, so every input of a chunk of up to M samples lies in earlier chunks and a whole
chunk is computed with a handful of numpy calls (no per-sample Python loop). `a` is solved in closed form
so the loop phase delay at the fundamental equals the period exactly (accurate tuning).

Master chain: voice sum -> optional "electric" tone (tanh drive + FIR tone filter) -> smoothed volume ->
peak limiter (ceiling, default -3 dBFS) -> final safety clip -> float32.

Threading: `handle`/`note_on`/`bend`/`all_off`/`render` must be called from one thread (the audio
callback). `set_volume` and `set_tone` only assign one attribute each and are safe from any thread.

Allocation notes: render() works in preallocated buffers with `out=` arguments. Residual temporaries:
small slice/view objects per numpy call, and in a note-on the excitation coloring (np.convolve and one
copy of at most one period, <= ~1.7k float64). render(out=None) allocates the returned array.
"""
from __future__ import annotations

import math

import numpy as np

from .events import AllOff, Bend, NoteOn, TONES

MIDI_MIN = 22.0          # lowest pitch the delay lines are sized for (after bend)
MIDI_MAX = 104.0         # highest pitch (keeps the loop delay >= ~15 samples at 48 kHz)
SILENCE = 2e-5           # voice peak below this -> voice released (also guards denormals)
MAX_VOICE_S = 20.0       # hard cap on the life of a voice
REPLUCK_FADE_MS = 4.0    # fade of the old voice when the same string is plucked again
STEAL_FADE_MS = 8.0      # fade of a stolen voice
BEND_TAU_MS = 8.0        # bend smoothing time constant
LIMITER_ATTACK = 48      # samples
LIMITER_RELEASE_S = 0.15
MAX_PENDING = 64

_IDLE, _ACTIVE, _FADING = 0, 1, 2
_LP5 = np.array([1.0, 4.0, 6.0, 4.0, 1.0]) / 16.0


def midi_to_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


class _Voice:
    __slots__ = ("state", "string", "note_id", "midi", "bend_target", "bend_cur", "hist", "w", "M",
                 "c0", "c1", "c2", "S", "t60", "peak", "start", "fade_rem", "fade_len")

    def __init__(self, hist_len: int) -> None:
        self.hist = np.zeros(hist_len, dtype=np.float64)
        self.state = _IDLE
        self.string = -1
        self.note_id = -1
        self.midi = 60.0
        self.bend_target = 0.0
        self.bend_cur = 0.0
        self.w = 0
        self.M = 2
        self.c0 = self.c1 = self.c2 = 0.0
        self.S = 0.5
        self.t60 = 1.0
        self.peak = 0.0
        self.start = 0
        self.fade_rem = 0
        self.fade_len = 1


class GuitarSynth:
    def __init__(self, sample_rate: int = 48000, polyphony: int = 8, volume: float = 0.5, tone: str = "clean",
                 ceiling_dbfs: float = -3.0, max_block: int = 2048, seed: int = 0) -> None:
        self.sample_rate = int(sample_rate)
        self.polyphony = max(1, int(polyphony))
        self.max_block = max(16, int(max_block))
        self.ceiling_dbfs = float(ceiling_dbfs)
        self.seed = int(seed)
        sr = self.sample_rate
        ceiling = 10.0 ** (self.ceiling_dbfs / 20.0)
        c32 = np.float32(ceiling)
        if float(c32) > ceiling:
            c32 = np.nextafter(c32, np.float32(0.0))
        self._clip = float(c32)                 # exactly representable in float32 and <= ceiling
        self._lim_target = ceiling * 0.97
        self._h0 = int(math.ceil(sr / midi_to_hz(MIDI_MIN))) + 4      # history needed behind the write head
        hist_len = 2 * self._h0 + 4 * self.max_block
        self._voices = [_Voice(hist_len) for _ in range(2 * self.polyphony)]   # extra slots hold fading voices
        self._rng = np.random.Generator(np.random.PCG64(self.seed))
        mb = self.max_block
        self._mix = np.zeros(mb, dtype=np.float64)
        self._tmp = np.zeros(mb, dtype=np.float64)
        self._tmp2 = np.zeros(mb, dtype=np.float64)
        self._elec = np.zeros(mb, dtype=np.float64)
        self._ext = np.zeros(mb + 2, dtype=np.float64)   # electric tone-filter input with 2 samples of state
        self._idx = np.arange(mb, dtype=np.float64)
        self._ex = np.zeros(self._h0, dtype=np.float64)
        self._pending: list[list] = []          # [start_sample, midi, velocity, note_id, string, bend]
        self._clock = 0                         # samples rendered so far
        self._vol_target = self._clamp_vol(volume)
        self._vol_cur = self._vol_target
        self._tone = tone if tone in TONES else "clean"
        self._elec_cur = 1.0 if self._tone == "electric" else 0.0
        self._lim_gain = 1.0
        self._lim_rel = 1.0 - math.exp(-1.0 / (LIMITER_RELEASE_S * sr))

    # ---------- control (thread-safe setters) ----------

    @staticmethod
    def _clamp_vol(v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.5
        if not math.isfinite(v):
            return 0.5
        return min(1.0, max(0.0, v))

    def set_volume(self, volume: float) -> None:
        self._vol_target = self._clamp_vol(volume)

    @property
    def volume(self) -> float:
        return self._vol_target

    def set_tone(self, tone: str) -> None:
        if tone in TONES:
            self._tone = tone

    @property
    def tone(self) -> str:
        return self._tone

    def with_sample_rate(self, sample_rate: int) -> "GuitarSynth":
        """A fresh synth with the same settings at another sample rate (audio device fallback)."""
        return GuitarSynth(sample_rate, self.polyphony, self._vol_target, self._tone, self.ceiling_dbfs,
                           self.max_block, self.seed)

    @property
    def active_voices(self) -> int:
        return sum(1 for v in self._voices if v.state == _ACTIVE)

    # ---------- events (audio thread) ----------

    def handle(self, event) -> None:
        t = type(event)
        if t is NoteOn:
            delay = int(round(max(0.0, float(event.delay_ms)) * self.sample_rate / 1000.0))
            self.note_on(event.midi, event.velocity, event.note_id, event.string, delay)
        elif t is Bend:
            self.bend(event.voice, event.semitones)
        elif t is AllOff:
            self.all_off(event.fade_ms)

    def note_on(self, midi: float, velocity: float, note_id: int, string: int = 0, delay_samples: int = 0) -> None:
        try:
            midi = float(midi)
            velocity = float(velocity)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(midi) and math.isfinite(velocity)):
            return
        midi = min(MIDI_MAX, max(MIDI_MIN, midi))
        velocity = min(1.0, max(0.0, velocity))
        start = self._clock + max(0, int(delay_samples))
        entry = [start, midi, velocity, int(note_id), int(string), 0.0]
        pend = self._pending
        i = len(pend)
        while i > 0 and pend[i - 1][0] > start:   # keep sorted, stable for equal starts
            i -= 1
        pend.insert(i, entry)
        if len(pend) > MAX_PENDING:
            pend.pop(0)

    def bend(self, note_id: int, semitones: float) -> None:
        try:
            s = float(semitones)
        except (TypeError, ValueError):
            return
        if not math.isfinite(s):
            return
        s = min(12.0, max(-12.0, s))
        for v in self._voices:
            if v.state != _IDLE and v.note_id == note_id:
                v.bend_target = s
        for e in self._pending:
            if e[3] == note_id:
                e[5] = s

    def all_off(self, fade_ms: float = 20.0) -> None:
        self._pending.clear()
        try:
            fade_ms = float(fade_ms)
        except (TypeError, ValueError):
            fade_ms = 20.0
        if not math.isfinite(fade_ms):
            fade_ms = 20.0
        n = max(1, int(round(max(0.0, fade_ms) * self.sample_rate / 1000.0)))
        for v in self._voices:
            if v.state != _IDLE:
                self._fade(v, n)

    # ---------- voice management ----------

    @staticmethod
    def _fade(v: _Voice, n: int) -> None:
        if v.state == _FADING:
            gain = v.fade_rem / v.fade_len
            rem = min(v.fade_rem, n)
            if gain <= 0.0 or rem <= 0:
                v.state = _IDLE
                return
            v.fade_rem = rem
            v.fade_len = rem / gain
        else:
            v.state = _FADING
            v.fade_rem = n
            v.fade_len = n

    def _tune(self, v: _Voice) -> None:
        sr = self.sample_rate
        m = min(MIDI_MAX, max(MIDI_MIN, v.midi + v.bend_cur))
        f = midi_to_hz(m)
        w0 = 2.0 * math.pi * f / sr
        S = v.S
        pd_s = math.atan2(S * math.sin(w0), 1.0 - S + S * math.cos(w0)) / w0
        D = sr / f - pd_s
        M = int(D)
        d = D - M
        if M < 2:
            M, d = 2, 0.0
        t = math.tan(d * w0)
        a = t / (math.sin(w0) + t * (1.0 - math.cos(w0))) if t > 0.0 else 0.0
        a = min(1.0, max(0.0, a))
        # per-period gain for the wanted T60, compensated for the loss/interpolation attenuation at the
        # fundamental (otherwise high notes die far too fast); stays < 1 so the loop is always stable
        cw, sw = math.cos(w0), math.sin(w0)
        h_loss = math.hypot(1.0 - S + S * cw, S * sw)
        h_interp = math.hypot(1.0 - a + a * cw, a * sw)
        g = min(0.99995, 0.001 ** (1.0 / (f * v.t60)) / max(1e-6, h_loss * h_interp))
        v.M = M
        v.c0 = g * (1.0 - S) * (1.0 - a)
        v.c1 = g * ((1.0 - S) * a + S * (1.0 - a))
        v.c2 = g * S * a

    def _trigger(self, midi: float, vel: float, note_id: int, string: int, bend: float) -> None:
        sr = self.sample_rate
        voices = self._voices
        for v in voices:                       # re-pluck: the string's old vibration is damped quickly
            if v.state == _ACTIVE and v.string == string:
                self._fade(v, max(1, int(REPLUCK_FADE_MS * sr / 1000.0)))
        active = [v for v in voices if v.state == _ACTIVE]
        if len(active) >= self.polyphony:      # steal the quietest (ties: oldest)
            victim = min(active, key=lambda x: (x.peak, x.start))
            self._fade(victim, max(1, int(STEAL_FADE_MS * sr / 1000.0)))
        slot = None
        for v in voices:
            if v.state == _IDLE:
                slot = v
                break
        if slot is None:                       # every slot busy fading: drop the most faded one
            slot = min((v for v in voices if v.state == _FADING), key=lambda x: x.fade_rem / x.fade_len)
        electric = self._tone == "electric"
        v = slot
        v.state = _ACTIVE
        v.string = string
        v.note_id = note_id
        v.midi = midi
        v.bend_target = bend
        v.bend_cur = bend
        v.start = self._clock
        # loss filter: darker low strings, brighter (less damped) high strings = decay stretch for highs
        S = min(0.5, max(0.12, 0.45 - 0.006 * (midi - 40.0)))
        v.S = S * (0.8 if electric else 1.0)
        v.t60 = 6.0 * 2.0 ** (-(midi - 40.0) / 24.0) * (1.6 if electric else 1.0)
        self._tune(v)
        # excitation: one period of colored noise written into the delay line
        P = sr / midi_to_hz(min(MIDI_MAX, max(MIDI_MIN, midi + bend)))
        L = v.M + 2
        ex = self._ex[:L]
        self._rng.random(out=ex)
        ex *= 2.0
        ex -= 1.0
        bright = min(1.0, 0.08 + 0.92 * vel ** 1.3 + (0.1 if electric else 0.0))
        lp = np.convolve(ex, _LP5, mode="same")
        lp = np.convolve(lp, _LP5, mode="same")
        ex *= bright
        ex += (1.0 - bright) * lp
        dp = max(1, int(round(0.13 * P)))      # pick position ~ 1/8 of the string
        if dp < L:
            prev = ex[: L - dp].copy()
            ex[dp:] -= prev
        # remove the loop's DC mode: with taps c0..c2 (normalized) the invariant of the recursion is
        # sum(last M samples) + (c1+c2)*y[-M-1] + c2*y[-M-2]; making it zero leaves no slowly decaying offset
        gs = v.c0 + v.c1 + v.c2
        w1 = (v.c1 + v.c2) / gs
        w2 = v.c2 / gs
        q = float(ex[2:].sum()) + w1 * float(ex[1]) + w2 * float(ex[0])
        ex -= q / (L - 2 + w1 + w2)
        peak = float(np.max(np.abs(ex)))
        amp = 0.45 * (0.1 + 0.9 * vel ** 1.4)
        if peak > 0.0:
            ex *= amp / peak
        h = v.hist
        h0 = self._h0
        h[: h0 - L] = 0.0
        h[h0 - L: h0] = ex
        v.w = h0
        v.peak = amp

    # ---------- rendering ----------

    def _render_voice(self, v: _Voice, mix_seg: np.ndarray, n: int) -> None:
        h = v.hist
        w = v.w
        h0 = self._h0
        if w + n > h.shape[0]:
            h[:h0] = h[w - h0: w]              # no overlap: w >= 2*h0
            w = h0
        tmp = self._tmp
        done = 0
        bend_alpha_base = 1.0 / (BEND_TAU_MS * self.sample_rate / 1000.0)
        while done < n:
            if v.bend_cur != v.bend_target:    # bend: retune per chunk, smoothed
                diff = v.bend_target - v.bend_cur
                step = min(1.0, v.M * bend_alpha_base)
                v.bend_cur = v.bend_target if abs(diff) < 1e-4 else v.bend_cur + diff * step
                self._tune(v)
            M = v.M
            L = M if M < n - done else n - done
            s = w + done
            dst = h[s: s + L]
            t = tmp[:L]
            np.multiply(h[s - M: s - M + L], v.c0, out=dst)
            np.multiply(h[s - M - 1: s - M - 1 + L], v.c1, out=t)
            dst += t
            np.multiply(h[s - M - 2: s - M - 2 + L], v.c2, out=t)
            dst += t
            done += L
        y = h[w: w + n]
        t = tmp[:n]
        np.abs(y, out=t)
        v.peak = float(t.max())
        if v.state == _FADING:
            g = self._tmp2[:n]
            np.subtract(v.fade_rem, self._idx[:n], out=g)
            g *= 1.0 / v.fade_len
            np.maximum(g, 0.0, out=g)
            g *= y
            mix_seg += g
            v.fade_rem -= n
            if v.fade_rem <= 0:
                v.state = _IDLE
        else:
            mix_seg += y
            if v.peak < SILENCE or self._clock - v.start > MAX_VOICE_S * self.sample_rate:
                v.state = _IDLE
        v.w = w + n

    def _render_segment(self, a: int, b: int) -> None:
        n = b - a
        if n <= 0:
            return
        seg = self._mix[a:b]
        for v in self._voices:
            if v.state != _IDLE:
                self._render_voice(v, seg, n)

    def _render_block(self, n: int, dst: np.ndarray) -> None:
        mix = self._mix[:n]
        mix.fill(0.0)
        pos = 0
        pend = self._pending
        clock = self._clock
        while pend and pend[0][0] < clock + n:
            e = pend.pop(0)
            rel = max(0, e[0] - clock)
            if rel > pos:
                self._render_segment(pos, rel)
                pos = rel
            self._trigger(e[1], e[2], e[3], e[4], e[5])
        self._render_segment(pos, n)
        self._clock = clock + n

        tmp = self._tmp[:n]
        idx = self._idx[:n]
        # tone: clean / electric with a one-block crossfade on change
        target = 1.0 if self._tone == "electric" else 0.0
        e0 = self._elec_cur
        if e0 > 0.0 or target > 0.0:
            ext = self._ext
            el = self._elec[:n]
            np.multiply(mix, 6.0, out=el)
            np.tanh(el, out=el)
            ext[2: n + 2] = el
            np.multiply(ext[0:n], 0.25 * 0.55, out=el)
            np.multiply(ext[1: n + 1], 0.5 * 0.55, out=tmp)
            el += tmp
            np.multiply(ext[2: n + 2], 0.25 * 0.55, out=tmp)
            el += tmp
            ext[0:2] = ext[n: n + 2]
            if e0 == target:
                mix[:] = el
            else:
                np.subtract(el, mix, out=el)
                np.multiply(idx, (target - e0) / n, out=tmp)
                tmp += e0
                el *= tmp
                mix += el
                self._elec_cur = target
        # volume (smoothed over the block)
        v0, v1 = self._vol_cur, self._vol_target
        if v0 == v1:
            mix *= v0
        else:
            np.multiply(idx, (v1 - v0) / n, out=tmp)
            tmp += v0
            mix *= tmp
            self._vol_cur = v1
        # limiter
        np.abs(mix, out=tmp)
        peak = float(tmp.max())
        if not math.isfinite(peak):            # never let instability reach the output
            for v in self._voices:
                v.state = _IDLE
                v.hist.fill(0.0)
            self._ext.fill(0.0)
            self._lim_gain = 1.0
            mix.fill(0.0)
            peak = 0.0
        g0 = self._lim_gain
        safe = self._lim_target / peak if peak > self._lim_target else 1.0
        if safe < g0:
            g1 = safe
            a = min(n, LIMITER_ATTACK)
            tmp[a:] = g1
            np.multiply(idx[:a], (g1 - g0) / a, out=tmp[:a])
            tmp[:a] += g0
            mix *= tmp
        else:
            g1 = min(safe, g0 + (1.0 - g0) * min(1.0, self._lim_rel * n))
            if g0 != 1.0 or g1 != 1.0:
                np.multiply(idx, (g1 - g0) / n, out=tmp)
                tmp += g0
                mix *= tmp
        self._lim_gain = g1
        np.clip(mix, -self._clip, self._clip, out=mix)
        np.copyto(dst, mix, casting="same_kind")

    def render(self, frames: int, out: "np.ndarray | None" = None) -> np.ndarray:
        """Render `frames` mono float32 samples (into `out[:frames]` when given)."""
        frames = max(0, int(frames))
        if out is None:
            out = np.empty(frames, dtype=np.float32)
        dst = out[:frames]
        pos = 0
        mb = self.max_block
        while pos < frames:
            k = min(mb, frames - pos)
            self._render_block(k, dst[pos: pos + k])
            pos += k
        return dst


__all__ = ["GuitarSynth", "midi_to_hz"]
