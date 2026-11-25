"""The "Serbest teller" layout: strings the user draws, moves and resizes. Stdlib only, pure, deterministic.

A string is a normalized segment (x0, y0, x1, y1) on the UNMIRRORED camera frame. Geometry that must look
right on screen (angles, distances) runs in an isotropic space: x is scaled by the frame aspect (w / h).

Hand gestures (`FreeEditor`), all with a pinch held for `hold_ms`:
- one hand on empty space: draw a new string from the pinch point to where the hand goes;
- one hand near a string end: drag that end (resize / rotate); near the string body: move the string;
- both hands: near the same string, grab its two ends; elsewhere, a new string between the hands.
Release the pinch to drop. A string shorter than MIN_LENGTH on release is removed (squeeze to delete).
Short tracking failures (hand missing, degraded, ambiguous or re-identified for at most `grace_ms`) freeze the
edit instead of ending it.

Snapping (optional, `snap=True`) only acts when the string is already close, so free placement stays
possible: near-horizontal/vertical angles straighten, and a string parallel to another one with one end
close to that one's end lines up with it (stacking); the gap then snaps to the existing stack gap. The length
decides the note, so snapping never changes it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from handcontrol.instrument.geometry import Vec, dist, lerp, point_segment_distance

Seg = tuple[float, float, float, float]

MAX_STRINGS = 10
MIN_LENGTH = 0.06          # isotropic units (fraction of the frame height)
GRAB_RADIUS = 0.06         # pinch point within this of a string body grabs it
END_RADIUS = 0.07          # ... within this of an end grabs that end
SNAP_ANGLE_DEG = 7.0
SNAP_END = 0.06            # stacked ends align when each is this close to the other string's end
SNAP_REACH = 0.30          # only strings at most this far (perpendicular) can be stacked on
SNAP_GAP = 0.025           # gap snaps to the stack gap when this close
REID_RADIUS = 0.15         # a new hand id pinching this close to a lost pinching hand is the same hand


def _iso(p: Vec, aspect: float) -> Vec:
    return (p[0] * aspect, p[1])


def _norm(p: Vec, aspect: float) -> Vec:
    return (p[0] / aspect, p[1])


def ends(seg: Seg) -> tuple[Vec, Vec]:
    return (seg[0], seg[1]), (seg[2], seg[3])


def seg_length(seg: Seg, aspect: float) -> float:
    a, b = ends(seg)
    return dist(_iso(a, aspect), _iso(b, aspect))


def clamp_seg(seg: Seg) -> Seg:
    return tuple(round(min(1.0, max(0.0, float(v))), 4) for v in seg)  # type: ignore[return-value]


def normalize_free_strings(raw: object, aspect: float = 4.0 / 3.0) -> tuple[Seg, ...]:
    """Validated strings: 4 finite numbers each, clamped into the frame, long enough, at most MAX_STRINGS.
    Anything malformed is dropped (settings can be hand-edited)."""
    out: list[Seg] = []
    try:
        items = list(raw)  # type: ignore[call-overload]
    except TypeError:
        return ()
    for item in items:
        try:
            vals = [float(v) for v in item]
        except (TypeError, ValueError):
            continue
        if len(vals) != 4 or not all(math.isfinite(v) for v in vals):
            continue
        seg = clamp_seg(tuple(vals))  # type: ignore[arg-type]
        if seg_length(seg, aspect) >= MIN_LENGTH:
            out.append(seg)
        if len(out) >= MAX_STRINGS:
            break
    return tuple(out)


def move_seg(seg: Seg, dx: float, dy: float) -> Seg:
    """Shifted copy that stays whole inside the frame."""
    x0, y0, x1, y1 = seg
    dx = min(1.0 - max(x0, x1), max(-min(x0, x1), dx))
    dy = min(1.0 - max(y0, y1), max(-min(y0, y1), dy))
    return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


def fit_seg(seg: Seg, strings: tuple[Seg, ...], index: Optional[int], aspect: float, snap: bool) -> tuple[Seg, bool]:
    """Edited string `index` clamped into the frame and, with `snap`, aligned to the other strings."""
    seg = clamp_seg(seg)
    if not snap or seg_length(seg, aspect) < MIN_LENGTH:
        return seg, False
    return snap_segment(seg, [s for i, s in enumerate(strings) if i != index], aspect)


def put_seg(strings: tuple[Seg, ...], index: Optional[int], seg: Seg) -> tuple[tuple[Seg, ...], int]:
    """Strings with `seg` at `index` (None: appended), and its index."""
    if index is None:
        return strings + (seg,), len(strings)
    return strings[:index] + (seg,) + strings[index + 1:], index


def drop_short(strings: tuple[Seg, ...], index: Optional[int], aspect: float) -> tuple[Seg, ...]:
    """Strings without `index` when it was squeezed below the minimum length."""
    if index is None or seg_length(strings[index], aspect) >= MIN_LENGTH:
        return strings
    return strings[:index] + strings[index + 1:]


def hit_test(strings: Iterable[Seg], p: Vec, aspect: float, *, end_radius: float = END_RADIUS,
             grab_radius: float = GRAB_RADIUS) -> Optional[tuple[int, str]]:
    """(index, "p0" | "p1" | "body") of the string under normalized point p, ends first; None if none."""
    q = _iso(p, aspect)
    best: Optional[tuple[float, int, str]] = None
    segs = list(strings)
    for i, s in enumerate(segs):
        a, b = (_iso(e, aspect) for e in ends(s))
        for part, e in (("p0", a), ("p1", b)):
            d = dist(q, e)
            if d <= end_radius and (best is None or d < best[0]):
                best = (d, i, part)
    if best is not None:
        return best[1], best[2]
    for i, s in enumerate(segs):
        a, b = (_iso(e, aspect) for e in ends(s))
        d = point_segment_distance(q, a, b)
        if d <= grab_radius and (best is None or d < best[0]):
            best = (d, i, "body")
    return (best[1], best[2]) if best is not None else None


def _angle(a: Vec, b: Vec) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _offset(pa: Vec, pb: Vec, ra: Vec, rb: Vec, n: Vec) -> float:
    """Distance of the midpoint of p from the midpoint of r along n."""
    return ((pa[0] + pb[0]) / 2.0 - (ra[0] + rb[0]) / 2.0) * n[0] + ((pa[1] + pb[1]) / 2.0 - (ra[1] + rb[1]) / 2.0) * n[1]


def _line_diff(t1: float, t2: float) -> float:
    """Smallest difference of two undirected line angles (0..pi/2)."""
    d = abs(t1 - t2) % math.pi
    return min(d, math.pi - d)


def snap_segment(seg: Seg, others: Iterable[Seg], aspect: float) -> tuple[Seg, bool]:
    """Snapped copy of seg and whether anything snapped. Only near-misses move; the rest is untouched."""
    a, b = (_iso(e, aspect) for e in ends(seg))
    snapped = False
    length = dist(a, b)
    if length < 1e-6:
        return seg, False
    mid = lerp(a, b, 0.5)
    theta = _angle(a, b)
    lim = math.radians(SNAP_ANGLE_DEG)
    for target in (0.0, math.pi / 2.0):
        if _line_diff(theta, target) < lim:
            # keep the direction (which end is which), straighten around the midpoint
            ux, uy = math.cos(theta), math.sin(theta)
            if target == 0.0:
                ux, uy = (1.0 if ux >= 0 else -1.0), 0.0
            else:
                ux, uy = 0.0, (1.0 if uy >= 0 else -1.0)
            h = length / 2.0
            a, b = (mid[0] - ux * h, mid[1] - uy * h), (mid[0] + ux * h, mid[1] + uy * h)
            theta = _angle(a, b)
            snapped = True
            break

    rest = [tuple(_iso(e, aspect) for e in ends(o)) for o in others]
    best = None
    for ra, rb in rest:
        r_theta = _angle(ra, rb)
        if _line_diff(theta, r_theta) >= lim or dist(ra, rb) < 1e-6:
            continue
        ux, uy = math.cos(r_theta), math.sin(r_theta)
        nx, ny = -uy, ux
        # map seg ends onto r's ends in the matching order
        pa, pb = (a, b) if (a[0] - b[0]) * ux + (a[1] - b[1]) * uy <= 0 else (b, a)
        off = _offset(pa, pb, ra, rb, (nx, ny))
        if abs(off) > SNAP_REACH or abs(off) < 1e-6:
            continue
        ta = (ra[0] + nx * off, ra[1] + ny * off)
        tb = (rb[0] + nx * off, rb[1] + ny * off)
        da, db = dist(pa, ta), dist(pb, tb)
        if min(da, db) <= SNAP_END and (best is None or abs(off) < abs(best[0])):
            best = (off, ra, rb, (ux, uy), pa is a, da <= db + 1e-9)
    if best is not None:
        off, ra, rb, (ux, uy), same, first = best
        gap = _stack_gap(ra, rb, rest)
        if gap is not None and abs(abs(off) - gap) < SNAP_GAP:
            off = math.copysign(gap, off)
        r, k = (ra, length) if first else (rb, -length)      # line up the closer end, keep the length
        ta = (r[0] - uy * off, r[1] + ux * off)
        tb = (ta[0] + ux * k, ta[1] + uy * k)
        if not first:
            ta, tb = tb, ta
        a, b = (ta, tb) if same else (tb, ta)
        snapped = True
    out = clamp_seg((*_norm(a, aspect), *_norm(b, aspect)))  # type: ignore[arg-type]
    return out, snapped


def _stack_gap(ra: Vec, rb: Vec, rest: list) -> Optional[float]:
    """Smallest perpendicular gap between string r and the strings already stacked on it (one end aligned)."""
    r_theta = _angle(ra, rb)
    ux, uy = math.cos(r_theta), math.sin(r_theta)
    gaps = []
    for qa, qb in rest:
        if (qa, qb) == (ra, rb) or _line_diff(_angle(qa, qb), r_theta) > 1e-3:
            continue
        off = _offset(qa, qb, ra, rb, (-uy, ux))
        aligned = any(abs((q[0] - r[0]) * ux + (q[1] - r[1]) * uy) < 1e-3 for q in (qa, qb) for r in (ra, rb))
        if aligned and abs(off) > 1e-3:
            gaps.append(abs(off))
    return min(gaps) if gaps else None


# ---------------------------------------------------------------------------- hand editing

@dataclass(frozen=True)
class HandPinch:
    hand_id: int
    point: Vec            # normalized pinch point (midpoint of thumb and index tips)
    distance_pu: float    # thumb-index distance in palm units
    usable: bool = True   # False: shaky frame, keeps a running pinch alive but cannot start one


@dataclass
class _Grab:
    hands: tuple[int, ...]
    index: Optional[int]                  # edited string, None = new string
    # per hand: (which end it drives: 0/1/"both", offset from the hand to that end in normalized units)
    links: dict[int, tuple[object, Vec, Vec]] = field(default_factory=dict)
    draft: Optional[Seg] = None
    snapped: bool = False


@dataclass(frozen=True)
class EditState:
    strings: tuple[Seg, ...]             # strings to show/play now (draft applied)
    active: Optional[int]                # index of the edited string in `strings`, None when idle
    editing: bool                        # a grab is engaged (no strikes)
    snapped: bool
    committed: bool                      # this step finished an edit (persist `strings`)
    pending: tuple[tuple[Vec, float], ...] = ()   # pinches waiting for the hold: (point, progress 0..1)
    full: bool = False                   # a new string was refused: MAX_STRINGS reached


class FreeEditor:
    def __init__(self, *, on_pu: float = 0.35, off_pu: float = 0.55, hold_ms: float = 400.0,
                 grace_ms: float = 250.0) -> None:
        self.on_pu, self.off_pu, self.hold_ms, self.grace_ms = on_pu, off_pu, hold_ms, grace_ms
        self.loose_pu = (on_pu + off_pu) / 2.0           # an opening pinch no longer moves the string
        self.reset()

    def reset(self) -> None:
        self._since: dict[int, tuple[float, Vec]] = {}    # hand id -> (pinch start ms, start point)
        self._seen: dict[int, tuple[float, Vec]] = {}     # hand id -> (last pinched frame ms, point)
        self._ok_t: Optional[float] = None                # last frame with certain tracking
        self._grab: Optional[_Grab] = None
        self._full_until = -1.0

    @property
    def editing(self) -> bool:
        return self._grab is not None

    def pinched_ids(self) -> set[int]:
        """Hands that are pinching now (they do not strike)."""
        return set(self._since)

    def step(self, strings: tuple[Seg, ...], pinches: list[HandPinch], t: float, aspect: float,
             snap: bool, allowed: bool = True, uncertain: bool = False) -> EditState:
        """`allowed=False` ends everything at once; `uncertain` (shaky tracking) only freezes for grace_ms."""
        if uncertain and (self._ok_t is None or t - self._ok_t > self.grace_ms):
            allowed = False
        if not uncertain:
            self._ok_t = t
        by_id = {} if uncertain else {p.hand_id: p for p in pinches if math.isfinite(p.distance_pu)}
        grab = self._grab
        if not allowed:
            self._since.clear()
            self._seen.clear()
        else:
            self._reidentify(by_id, aspect)
            # pinch hysteresis per hand; a hand that vanished keeps its pinch for grace_ms
            for hid in list(self._since):
                p = by_id.get(hid)
                if p is None:
                    if t - self._seen[hid][0] > self.grace_ms:
                        self._drop(hid)
                elif p.distance_pu > self.off_pu:
                    self._drop(hid)
                else:
                    self._seen[hid] = (t, p.point)
            for p in by_id.values():
                if p.hand_id not in self._since and p.usable and p.distance_pu < self.on_pu:
                    self._since[p.hand_id] = (t, p.point)
                    self._seen[p.hand_id] = (t, p.point)

        if grab is not None:
            if not allowed or any(h not in self._since for h in grab.hands):
                return self._commit(strings, aspect, t)
            if all(h in by_id and by_id[h].distance_pu <= self.loose_pu for h in grab.hands):
                self._move(grab, by_id, strings, aspect, snap)
            return self._state(strings, grab)

        ready = [h for h, (t0, _) in self._since.items() if t - t0 >= self.hold_ms and h in by_id]
        if ready and allowed:
            first = ready[0]
            others = [h for h in self._since if h != first and h in by_id]
            hands = (first, others[0]) if others else (first,)
            grab = self._start(strings, hands, by_id, aspect, t)
            if grab is not None:
                self._grab = grab
                self._move(grab, by_id, strings, aspect, snap)
                return self._state(strings, grab)
        pending = tuple((pt, min(1.0, (t - t0) / self.hold_ms)) for t0, pt in self._since.values())
        return EditState(strings, None, False, False, False, pending, t < self._full_until)

    # -- internals

    def _drop(self, hid: int) -> None:
        self._since.pop(hid, None)
        self._seen.pop(hid, None)

    def _reidentify(self, by_id: dict[int, HandPinch], aspect: float) -> None:
        """The tracker gave a lost pinching hand a new id: carry its pinch (and grab) over."""
        for old in [h for h in self._since if h not in by_id]:
            last = _iso(self._seen[old][1], aspect)
            near = [p for h, p in by_id.items() if h not in self._since and p.distance_pu <= self.off_pu
                    and dist(_iso(p.point, aspect), last) <= REID_RADIUS]
            if len(near) != 1:
                continue
            new = near[0].hand_id
            self._since[new] = self._since.pop(old)
            self._seen[new] = self._seen.pop(old)
            g = self._grab
            if g is not None and old in g.links:
                g.links[new] = g.links.pop(old)
                g.hands = tuple(new if h == old else h for h in g.hands)

    def _start(self, strings: tuple[Seg, ...], hands: tuple[int, ...], by_id: dict[int, HandPinch],
               aspect: float, t: float) -> Optional[_Grab]:
        pts = [by_id[h].point for h in hands]
        hits = [hit_test(strings, p, aspect) for p in pts]
        if None in hits or len({hit[0] for hit in hits}) > 1:      # new string  # type: ignore[index]
            if len(strings) >= MAX_STRINGS:
                self._full_until = t + 1500.0
                return None
            parts = ("draw",) if len(hands) == 1 else (0, 1)
            return _Grab(hands, None, {h: (part, p, (0.0, 0.0)) for h, p, part in zip(hands, pts, parts)})
        i, part = hits[0]  # type: ignore[misc]
        e = ends(strings[i])
        if len(hands) == 2:                      # each hand drives its nearer end (no crossing)
            def way(a: int, b: int) -> float:
                return sum(dist(_iso(p, aspect), _iso(e[k], aspect)) for p, k in zip(pts, (a, b)))
            order = (0, 1) if way(0, 1) <= way(1, 0) else (1, 0)
        elif part == "body":
            return _Grab(hands, i, {hands[0]: ("both", pts[0], (0.0, 0.0))})
        else:
            order = (0 if part == "p0" else 1,)
        return _Grab(hands, i, {h: (end, p, (e[end][0] - p[0], e[end][1] - p[1]))
                                for h, p, end in zip(hands, pts, order)})

    def _move(self, g: _Grab, by_id: dict[int, HandPinch], strings: tuple[Seg, ...], aspect: float,
              snap: bool) -> None:
        base = strings[g.index] if g.index is not None else None
        e = list(ends(base)) if base is not None else [None, None]
        for h, (end, p0, off) in g.links.items():
            p = by_id[h].point
            if end == "draw":
                e = [p0, p]
            elif end == "both":
                assert base is not None
                e = list(ends(move_seg(base, p[0] - p0[0], p[1] - p0[1])))
            else:
                e[end] = (p[0] + off[0], p[1] + off[1])  # type: ignore[index]
        g.draft, g.snapped = fit_seg((*e[0], *e[1]), strings, g.index, aspect, snap)  # type: ignore[misc]

    def _apply(self, strings: tuple[Seg, ...], g: _Grab) -> tuple[tuple[Seg, ...], Optional[int]]:
        return (strings, g.index) if g.draft is None else put_seg(strings, g.index, g.draft)

    def _state(self, strings: tuple[Seg, ...], g: _Grab) -> EditState:
        shown, idx = self._apply(strings, g)
        return EditState(shown, idx, True, g.snapped, False)

    def _commit(self, strings: tuple[Seg, ...], aspect: float, t: float) -> EditState:
        g, self._grab = self._grab, None
        assert g is not None
        # the hands that are still pinching must start a new hold before grabbing again
        for h in list(self._since):
            self._since[h] = (t, self._since[h][1])
        out = drop_short(*self._apply(strings, g), aspect)
        return EditState(out, None, False, False, out != strings)


__all__ = [
    "END_RADIUS", "EditState", "FreeEditor", "GRAB_RADIUS", "HandPinch", "MAX_STRINGS", "MIN_LENGTH", "REID_RADIUS", "Seg",
    "clamp_seg", "drop_short", "ends", "fit_seg", "hit_test", "move_seg", "normalize_free_strings",
    "put_seg", "seg_length", "snap_segment",
]
