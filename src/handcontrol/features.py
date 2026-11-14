"""Per-hand, per-finger features from raw tracking samples (spec section 4). Stdlib only.

Pipeline per FrameSample:
  1. drop hands that cannot be located (landmark count != 21, non-finite palm landmarks);
  2. assign stable hand IDs (palm proximity + palm scale, handedness only as a soft signal);
  3. quality per hand: geometry plausibility, temporal discontinuity, identity ambiguity, latency;
  4. per finger curl 0..1 and EXTENDED/BENT/UNKNOWN with hysteresis and time-based dwell.

Geometry notes:
  - Image-space distances (palm scale, palm center, pinch) use pixels: x*width, y*height.
  - Joint angles use 3D points: world landmarks when present and valid, else (x*w, y*h, z*w).
    MediaPipe z is approximate; it only feeds angles/ratios, never metric distances between hands.
  - Missing hands are never extrapolated. Output landmarks/curls are raw (unfiltered);
    use filters.OneEuroFilter2D downstream for the pointer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from handcontrol.contracts import (
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    FrameSample,
    HandFeatures,
    HandSample,
    Handedness,
    Landmark,
    Quality,
)
from handcontrol.filters import DwellLatch

WRIST = 0
PALM_MCPS = (5, 9, 13, 17)
FINGER_ORDER = (FingerName.THUMB, FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)
FINGER_CHAINS: dict[FingerName, tuple[int, int, int, int]] = {
    FingerName.THUMB: (1, 2, 3, 4),
    FingerName.INDEX: (5, 6, 7, 8),
    FingerName.MIDDLE: (9, 10, 11, 12),
    FingerName.RING: (13, 14, 15, 16),
    FingerName.LITTLE: (17, 18, 19, 20),
}
_LOCATING = (WRIST,) + PALM_MCPS

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]


@dataclass(frozen=True)
class FeatureConfig:
    # --- palm ---
    palm_width_ratio: float = 0.70        # expected |MCP5-MCP17| / |wrist-MCP9|
    min_palm_px: float = 12.0             # below -> UNKNOWN
    degraded_palm_px: float = 30.0        # below -> DEGRADED (hand too far / too small)
    max_palm_frame_frac: float = 0.9      # palm larger than this * min(w, h) -> DEGRADED
    palm_aspect_min: float = 0.35         # 2D/3D palm length vs width balance; below -> DEGRADED (edge-on)
    use_depth: bool = True                # use MediaPipe z for joint angles
    depth_scale: float = 1.0              # z is scaled like x (z * width)
    prefer_world_landmarks: bool = True
    # --- plausibility (3D, palm units) ---
    min_bone_ratio: float = 0.05          # a finger bone shorter than this -> that finger UNKNOWN
    bone_ratio_range: tuple[float, float] = (0.08, 0.80)
    finger_length_range: tuple[float, float] = (0.35, 1.60)
    # --- index..little ---
    max_flex_deg: float = 250.0           # MCP+PIP+DIP flexion of a full fist
    reach_fist: float = -0.2              # (|tip-wrist|-|mcp-wrist|)/finger length in a fist
    angle_weight: float = 0.6             # curl = w*angle_curl + (1-w)*reach_curl
    disagreement_max: float = 0.5         # |angle_curl - reach_curl| above -> UNKNOWN
    # --- thumb (own joint/opposition geometry) ---
    thumb_max_flex_deg: float = 110.0     # MCP+IP flexion when tucked
    thumb_open_dist: float = 0.85         # tip to palm center, palm units, thumb open
    thumb_tucked_dist: float = 0.40       # tip to palm center, palm units, thumb across palm
    thumb_angle_weight: float = 0.6
    thumb_disagreement_max: float = 0.6
    # --- state hysteresis + dwell ---
    extend_curl: float = 0.30             # curl <= -> EXTENDED candidate
    bend_curl: float = 0.50               # curl >= -> BENT candidate; between: hold
    switch_dwell_ms: float = 80.0         # EXTENDED <-> BENT
    acquire_dwell_ms: float = 50.0        # UNKNOWN -> EXTENDED/BENT
    # --- temporal discontinuity ---
    disc_min_palm: float = 0.75           # jumps smaller than this never count
    disc_speed_palm_s: float = 30.0       # palm-center speed above this -> discontinuity
    disc_scale_ratio: float = 1.5         # palm scale change factor between samples
    disc_scale_window_ms: float = 200.0
    disc_hold_ms: float = 150.0           # hand stays DEGRADED this long after a discontinuity
    max_processing_ms: float = 150.0      # inference_done - capture above -> DEGRADED
    # --- identity ---
    max_hands: int = 2
    gate_min_palm: float = 1.5
    gate_speed_palm_s: float = 60.0
    gate_max_palm: float = 6.0
    gate_scale_ratio: float = 2.0
    scale_weight: float = 1.0
    handedness_weight: float = 0.6        # soft penalty * handedness_score when labels differ
    ambiguity_margin: float = 0.35        # alternative assignment cost within this -> ambiguous
    overlap_palm: float = 0.7             # palm centers closer than this (palm units) -> ambiguous
    same_handedness_min_score: float = 0.5
    ambiguity_hold_ms: float = 100.0
    # a recently seen track that vanishes while a detection is this close to it (palm units) is a
    # merge (palms overlapping, tracker reports one hand): identity of the remaining hand is ambiguous
    merge_palm: float = 1.0
    merge_window_ms: float = 250.0
    track_memory_ms: float = 500.0        # a lost hand may reclaim its ID within this time
    latch_reset_gap_ms: float = 200.0     # finger states restart after an absence this long


# ---------------- vector helpers ----------------

def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a: Vec3) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _dist(a: Vec3, b: Vec3) -> float:
    return _norm(_sub(a, b))


def _dist2(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _angle_deg(u: Vec3, v: Vec3) -> float:
    nu, nv = _norm(u), _norm(v)
    if nu <= 0 or nv <= 0:
        return float("nan")
    c = (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _finite_lm(lm: Landmark) -> bool:
    return math.isfinite(lm.x) and math.isfinite(lm.y) and math.isfinite(lm.z)


_QRANK = {Quality.USABLE: 0, Quality.DEGRADED: 1, Quality.UNKNOWN: 2}


def _worst(a: Quality, b: Quality) -> Quality:
    return a if _QRANK[a] >= _QRANK[b] else b


# ---------------- per-detection measurement ----------------

@dataclass
class _Det:
    sample: HandSample
    px: list[Vec2]
    center: Vec2
    scale: float          # 2D palm scale in px; 0.0 when invalid
    all_finite: bool


def _measure(hand: HandSample, w: int, h: int) -> Optional[_Det]:
    lms = hand.landmarks
    if len(lms) != 21:
        return None
    if not all(_finite_lm(lms[i]) for i in _LOCATING):
        return None
    px = [(lm.x * w, lm.y * h) for lm in lms]
    center = (sum(px[i][0] for i in PALM_MCPS) / 4.0, sum(px[i][1] for i in PALM_MCPS) / 4.0)
    return _Det(hand, px, center, 0.0, all(_finite_lm(lm) for lm in lms))


def _palm_scale(length: float, width: float, ratio: float) -> float:
    return max(length, width / ratio)


# ---------------- tracks ----------------

@dataclass
class _Track:
    hand_id: int
    center: Vec2
    scale: float
    handedness: Handedness
    last_seen_ms: float
    latches: list[DwellLatch] = field(default_factory=lambda: [DwellLatch(FingerState.UNKNOWN) for _ in FINGER_ORDER])
    disc_until_ms: float = -math.inf
    amb_until_ms: float = -math.inf

    def reset_latches(self) -> None:
        for latch in self.latches:
            latch.reset(FingerState.UNKNOWN)


class FeatureExtractor:
    def __init__(self, config: FeatureConfig = FeatureConfig()) -> None:
        self.config = config
        self._next_id = 1
        self._tracks: list[_Track] = []
        # diagnostics only (no effect on output): reason codes of the last update() call
        self.last_reasons: dict[int, tuple[str, ...]] = {}
        self.last_frame_reasons: tuple[str, ...] = ()

    def reset(self) -> None:
        """Forget all tracks and finger states. IDs are never reused, even after reset."""
        self._tracks = []

    # ---------- main entry ----------

    def update(self, sample: FrameSample) -> FrameFeatures:
        cfg = self.config
        self.last_reasons = {}
        self.last_frame_reasons = ()
        t = sample.capture_ms
        w, h = sample.width, sample.height
        try:
            valid = math.isfinite(t) and w > 0 and h > 0
        except TypeError:
            valid = False
        if not valid:
            self.last_frame_reasons = ("invalid_sample",)
            return self._tagged(FrameFeatures(sample.capture_ms, sample.inference_done_ms, w, h, (), False))

        self._tracks = [tr for tr in self._tracks if t - tr.last_seen_ms <= cfg.track_memory_ms]

        ambiguous = len(sample.hands) > cfg.max_hands
        frame_reasons: list[str] = ["too_many_hands"] if ambiguous else []
        dets: list[_Det] = []
        for hand in sample.hands[: cfg.max_hands]:
            det = _measure(hand, w, h)
            if det is None:
                frame_reasons.append("hand_unlocatable")
                continue
            p = det.px
            s = _palm_scale(_dist2(p[0], p[9]), _dist2(p[5], p[17]), cfg.palm_width_ratio)
            det.scale = s if math.isfinite(s) and s >= cfg.min_palm_px else 0.0
            dets.append(det)

        mapping, assign_ambiguous = self._associate(dets, t, min(w, h))
        if assign_ambiguous:
            frame_reasons.append("identity_ambiguous")
        pair_reason = self._pair_ambiguous(dets, min(w, h))
        if pair_reason:
            frame_reasons.append(pair_reason)
        merged = self._merge_ambiguous(dets, mapping, t, min(w, h))
        if merged:
            frame_reasons.append("merge")
        ambiguous = ambiguous or assign_ambiguous or bool(pair_reason) or merged

        latency = sample.inference_done_ms - sample.capture_ms
        slow = not math.isfinite(latency) or latency > cfg.max_processing_ms

        out: list[HandFeatures] = []
        frame_ambiguous = ambiguous
        for i, det in enumerate(dets):
            ti = mapping[i]
            if ti is None:
                track = _Track(self._next_id, det.center, det.scale, det.sample.handedness, t)
                self._next_id += 1
                self._tracks.append(track)
                disc_reason: Optional[str] = None
            else:
                track = self._tracks[ti]
                disc_reason = self._temporal_check(track, det, t)
            discontinuous = disc_reason is not None
            if ambiguous:
                track.amb_until_ms = t + cfg.ambiguity_hold_ms
            if discontinuous:
                track.disc_until_ms = t + cfg.disc_hold_ms
            in_amb = t < track.amb_until_ms or ambiguous
            frame_ambiguous = frame_ambiguous or in_amb

            reasons: list[str] = []
            if in_amb:
                reasons.append("identity_ambiguous" if ambiguous else "ambiguity_hold")
            if disc_reason is not None:
                reasons.append(disc_reason)
            elif t < track.disc_until_ms:
                reasons.append("discontinuity_hold")
            hf = self._hand_features(det, track, sample, t, slow, in_amb, t < track.disc_until_ms or discontinuous,
                                     reasons)
            if hf.quality is not Quality.USABLE and reasons:
                self.last_reasons[hf.hand_id] = tuple(dict.fromkeys(reasons))
            out.append(hf)

            track.center = det.center
            if det.scale > 0:
                track.scale = det.scale
            if det.sample.handedness is not Handedness.UNKNOWN:
                track.handedness = det.sample.handedness
            track.last_seen_ms = t

        out.sort(key=lambda f: f.hand_id)
        self.last_frame_reasons = tuple(dict.fromkeys(frame_reasons))
        return self._tagged(FrameFeatures(sample.capture_ms, sample.inference_done_ms, w, h, tuple(out),
                                          frame_ambiguous))

    def _tagged(self, ff: FrameFeatures) -> FrameFeatures:
        """Attach the reason codes as a non-field attribute (ignored by ==, repr and the contract)."""
        try:
            object.__setattr__(ff, "reasons", (dict(self.last_reasons), self.last_frame_reasons))
        except Exception:  # noqa: BLE001 - diagnostics must never break tracking
            pass
        return ff

    # ---------- identity ----------

    def _pair_cost(self, det: _Det, tr: _Track, t: float, frame_min: float) -> Optional[float]:
        cfg = self.config
        ref = tr.scale if tr.scale > 0 else det.scale if det.scale > 0 else 0.1 * frame_min
        d = _dist2(det.center, tr.center) / ref
        dt_s = max(0.0, t - tr.last_seen_ms) / 1000.0
        gate = min(cfg.gate_max_palm, max(cfg.gate_min_palm, cfg.gate_speed_palm_s * dt_s))
        if d > gate:
            return None
        cost = d
        if det.scale > 0 and tr.scale > 0:
            lr = abs(math.log(det.scale / tr.scale))
            if lr > math.log(cfg.gate_scale_ratio):
                return None
            cost += cfg.scale_weight * lr
        hd = det.sample.handedness
        if hd is not Handedness.UNKNOWN and tr.handedness is not Handedness.UNKNOWN and hd is not tr.handedness:
            score = det.sample.handedness_score
            score = _clamp01(score) if math.isfinite(score) else 0.0
            cost += cfg.handedness_weight * score
        return cost

    def _associate(self, dets: list[_Det], t: float, frame_min: float) -> tuple[list[Optional[int]], bool]:
        if not dets:
            return [], False
        costs = [[self._pair_cost(d, tr, t, frame_min) for tr in self._tracks] for d in dets]
        options: list[tuple[int, float, tuple[Optional[int], ...]]] = []

        def walk(i: int, used: frozenset[int], acc: float, matched: int, cur: tuple[Optional[int], ...]) -> None:
            if i == len(dets):
                options.append((matched, acc, cur))
                return
            walk(i + 1, used, acc, matched, cur + (None,))
            for j, c in enumerate(costs[i]):
                if c is not None and j not in used:
                    walk(i + 1, used | {j}, acc + c, matched + 1, cur + (j,))

        walk(0, frozenset(), 0.0, 0, ())
        options.sort(key=lambda o: (-o[0], o[1]))
        best_n, best_cost, best = options[0]
        ambiguous = False
        for n, c, alt in options[1:]:
            if n != best_n or c - best_cost >= self.config.ambiguity_margin:
                continue
            if any(a is not None and a != b for a, b in zip(alt, best)):
                ambiguous = True
                break
        return list(best), ambiguous

    def _pair_ambiguous(self, dets: list[_Det], frame_min: float) -> str:
        """Reason code ('same_handedness' / 'overlap'), or '' when the pair is unambiguous."""
        cfg = self.config
        for i in range(len(dets)):
            for j in range(i + 1, len(dets)):
                a, b = dets[i], dets[j]
                ha, hb = a.sample.handedness, b.sample.handedness
                if (ha is hb and ha is not Handedness.UNKNOWN
                        and a.sample.handedness_score >= cfg.same_handedness_min_score
                        and b.sample.handedness_score >= cfg.same_handedness_min_score):
                    return "same_handedness"
                ref = max(a.scale, b.scale)
                ref = ref if ref > 0 else 0.1 * frame_min
                if _dist2(a.center, b.center) / ref < cfg.overlap_palm:
                    return "overlap"
        return ""

    def _merge_ambiguous(self, dets: list[_Det], mapping: list[Optional[int]], t: float, frame_min: float) -> bool:
        """A track seen moments ago is unmatched while a detection sits on top of it: two hands merged."""
        cfg = self.config
        matched = {m for m in mapping if m is not None}
        for j, tr in enumerate(self._tracks):
            if j in matched or t - tr.last_seen_ms > cfg.merge_window_ms:
                continue
            ref = tr.scale if tr.scale > 0 else 0.1 * frame_min
            if any(_dist2(d.center, tr.center) / ref < cfg.merge_palm for d in dets):
                return True
        return False

    # ---------- temporal ----------

    def _temporal_check(self, track: _Track, det: _Det, t: float) -> Optional[str]:
        """Reason code when the matched detection jumped implausibly since the previous sample."""
        cfg = self.config
        dt = t - track.last_seen_ms
        if dt > cfg.latch_reset_gap_ms:
            track.reset_latches()       # the hand was away: states restart, no jump judgement
            return None
        ref = track.scale if track.scale > 0 else det.scale
        if ref <= 0:
            return None
        d = _dist2(det.center, track.center) / ref
        dt_s = max(dt, 1.0) / 1000.0
        if d > cfg.disc_min_palm and d / dt_s > cfg.disc_speed_palm_s:
            return "discontinuity_speed"
        if det.scale > 0 and track.scale > 0 and dt <= cfg.disc_scale_window_ms:
            if abs(math.log(det.scale / track.scale)) > math.log(cfg.disc_scale_ratio):
                return "discontinuity_scale"
        return None

    # ---------- geometry ----------

    def _geo_points(self, hand: HandSample, w: int, h: int) -> list[Vec3]:
        cfg = self.config
        wl = hand.world_landmarks
        if cfg.prefer_world_landmarks and wl is not None and len(wl) == 21 and all(_finite_lm(p) for p in wl):
            return [(p.x, p.y, p.z) for p in wl]
        zs = w * cfg.depth_scale if cfg.use_depth else 0.0
        return [(p.x * w, p.y * h, p.z * zs) for p in hand.landmarks]

    def _plausibility(self, g: list[Vec3], palm: float, det: _Det, reasons: list[str]) -> Quality:
        cfg = self.config
        q = Quality.USABLE
        lo, hi = cfg.bone_ratio_range
        flo, fhi = cfg.finger_length_range
        for name in FINGER_ORDER:
            pts = [g[k] for k in FINGER_CHAINS[name]]
            bones = [_dist(pts[k], pts[k + 1]) / palm for k in range(3)]
            if any(not (lo <= b <= hi) for b in bones) or not (flo <= sum(bones) <= fhi):
                q = Quality.DEGRADED
                if "bone_ratio" not in reasons:
                    reasons.append("bone_ratio")
        p = det.px
        aspect2d = (_dist2(p[5], p[17]) / cfg.palm_width_ratio) / max(_dist2(p[0], p[9]), 1e-9)
        aspect3d = (_dist(g[5], g[17]) / cfg.palm_width_ratio) / max(_dist(g[0], g[9]), 1e-12)
        for a in (aspect2d, aspect3d):
            if not (cfg.palm_aspect_min <= a <= 1.0 / cfg.palm_aspect_min):
                q = Quality.DEGRADED
                if "palm_edge_on" not in reasons:
                    reasons.append("palm_edge_on")
        return q

    def _finger_curl(self, g: list[Vec3], name: FingerName, palm: float, palm_center: Vec3) -> tuple[float, bool]:
        """Return (curl, uncertain)."""
        cfg = self.config
        a, b, c, d = (g[k] for k in FINGER_CHAINS[name])
        bones = (_dist(a, b), _dist(b, c), _dist(c, d))
        if min(bones) < cfg.min_bone_ratio * palm:
            return 0.0, True
        if name is FingerName.THUMB:
            flex = _angle_deg(_sub(b, a), _sub(c, b)) + _angle_deg(_sub(c, b), _sub(d, c))
            if not math.isfinite(flex):
                return 0.0, True
            angle_curl = _clamp01(flex / cfg.thumb_max_flex_deg)
            dist = _dist(d, palm_center) / palm
            span = cfg.thumb_open_dist - cfg.thumb_tucked_dist
            opp_curl = _clamp01((cfg.thumb_open_dist - dist) / span)
            wa = cfg.thumb_angle_weight
            curl = wa * angle_curl + (1 - wa) * opp_curl
            return curl, abs(angle_curl - opp_curl) > cfg.thumb_disagreement_max
        wr = g[WRIST]
        if _dist(a, wr) < cfg.min_bone_ratio * palm:
            return 0.0, True
        flex = (_angle_deg(_sub(a, wr), _sub(b, a)) + _angle_deg(_sub(b, a), _sub(c, b))
                + _angle_deg(_sub(c, b), _sub(d, c)))
        if not math.isfinite(flex):
            return 0.0, True
        angle_curl = _clamp01(flex / cfg.max_flex_deg)
        reach = (_dist(d, wr) - _dist(a, wr)) / sum(bones)
        reach_curl = _clamp01((1.0 - reach) / (1.0 - cfg.reach_fist))
        wa = cfg.angle_weight
        curl = wa * angle_curl + (1 - wa) * reach_curl
        return curl, abs(angle_curl - reach_curl) > cfg.disagreement_max

    def _hand_features(self, det: _Det, track: _Track, sample: FrameSample, t: float, slow: bool,
                       in_amb: bool, discontinuous: bool, reasons: list[str]) -> HandFeatures:
        cfg = self.config
        w, h = sample.width, sample.height
        hand = det.sample
        quality = Quality.USABLE
        curls: list[tuple[float, bool]] = [(0.0, True)] * 5
        pinch = math.inf

        if not det.all_finite or det.scale <= 0:
            quality = Quality.UNKNOWN
            reasons.append("landmarks_nonfinite" if not det.all_finite else "palm_tiny")
        else:
            g = self._geo_points(hand, w, h)
            palm_geo = _palm_scale(_dist(g[0], g[9]), _dist(g[5], g[17]), cfg.palm_width_ratio)
            if not math.isfinite(palm_geo) or palm_geo <= 1e-9:
                quality = Quality.UNKNOWN
                reasons.append("palm_geo_invalid")
            else:
                quality = self._plausibility(g, palm_geo, det, reasons)
                if det.scale < cfg.degraded_palm_px:
                    quality = _worst(quality, Quality.DEGRADED)
                    reasons.append("palm_small")
                elif det.scale > cfg.max_palm_frame_frac * min(w, h):
                    quality = _worst(quality, Quality.DEGRADED)
                    reasons.append("palm_large")
                pc = tuple(sum(g[i][k] for i in PALM_MCPS) / 4.0 for k in range(3))
                curls = [self._finger_curl(g, n, palm_geo, pc) for n in FINGER_ORDER]  # type: ignore[arg-type]
                pinch = _dist2(det.px[4], det.px[8]) / det.scale
        if slow:
            reasons.append("slow_processing")
        if slow or discontinuous or in_amb:
            quality = _worst(quality, Quality.DEGRADED)

        fingers: list[FingerInfo] = []
        for idx, name in enumerate(FINGER_ORDER):
            latch = track.latches[idx]
            curl, uncertain = curls[idx]
            if quality is Quality.UNKNOWN or uncertain or in_amb or discontinuous:
                state = latch.force(FingerState.UNKNOWN)
            else:
                state = self._finger_state(latch, curl, t)
            fingers.append(FingerInfo(name, state, curl))

        px = det.px
        return HandFeatures(
            hand_id=track.hand_id,
            handedness=hand.handedness,
            quality=quality,
            palm_center_px=det.center,
            palm_scale_px=det.scale,
            fingers=tuple(fingers),
            pinch_distance=pinch,
            index_tip_px=px[8],
            landmarks=tuple(hand.landmarks),
        )

    def _finger_state(self, latch: DwellLatch, curl: float, t: float) -> FingerState:
        cfg = self.config
        current = latch.state
        if curl <= cfg.extend_curl:
            proposal = FingerState.EXTENDED
        elif curl >= cfg.bend_curl:
            proposal = FingerState.BENT
        else:
            proposal = current            # inside the hysteresis band: hold (UNKNOWN stays UNKNOWN)
        dwell = cfg.acquire_dwell_ms if current is FingerState.UNKNOWN else cfg.switch_dwell_ms
        return latch.update(proposal, t, dwell)


def finger(features: HandFeatures, name: FingerName) -> FingerInfo:
    """Convenience lookup by finger name."""
    return features.fingers[FINGER_ORDER.index(name)]


__all__: Sequence[str] = (
    "FeatureConfig",
    "FeatureExtractor",
    "FINGER_CHAINS",
    "FINGER_ORDER",
    "PALM_MCPS",
    "finger",
)
