"""Open-palm swipe recognizer and the COMMANDS mode profile tables (pure, stdlib + contracts only).

Direction is from the USER's point of view. Landmarks (and palm_center_px) are on the UNMIRRORED
camera frame and the camera faces the user, so the user moving the hand to their own LEFT
INCREASES image x; up is decreasing image y. The preview mirror setting does not change this.

A swipe: the dominant hand with an open palm (>= 3 of index..little EXTENDED) whose palm center
travels >= min_travel_pu palm units within max_window_ms, with the dominant axis at least
axis_ratio times the other one and a peak frame-to-frame speed >= min_peak_speed_pu_s. After a
swipe nothing fires for cooldown_ms and the opposite direction stays locked for opposite_lock_ms:
motion made inside those spans never counts as the start of a later swipe, so the return stroke
of a swipe does not fire.

Rest arm: the recognizer starts disarmed and is disarmed again by every fire and every reset (mode
entry, tracking gap, pinch, ...). It re-arms only once the palm has been at rest (frame-to-frame
speed below rest_speed_pu_s) continuously for rest_arm_ms; motion from before that rest never counts.
Vertical swipes (Task View / Show Desktop) are stricter: travel >= vertical_min_travel_pu, and the
motion must start from a rest of at least vertical_rest_ms, so lowering or raising the hand after
any activity, or a hand entering the frame, does not fire.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from handcontrol.contracts import FingerName, FingerState, HandFeatures, KeyCommand, Quality


class SwipeDirection(Enum):
    LEFT = "left"      # user's left (image x increases)
    RIGHT = "right"    # user's right (image x decreases)
    UP = "up"
    DOWN = "down"


_OPPOSITE = {
    SwipeDirection.LEFT: SwipeDirection.RIGHT,
    SwipeDirection.RIGHT: SwipeDirection.LEFT,
    SwipeDirection.UP: SwipeDirection.DOWN,
    SwipeDirection.DOWN: SwipeDirection.UP,
}


@dataclass(frozen=True)
class SwipeConfig:
    min_travel_pu: float = 1.2
    max_window_ms: float = 400.0
    axis_ratio: float = 2.0
    min_peak_speed_pu_s: float = 3.0
    cooldown_ms: float = 500.0
    opposite_lock_ms: float = 700.0
    min_open_fingers: int = 3
    max_gap_ms: float = 150.0      # a longer pause between frames is a tracking gap: history dropped
    rest_speed_pu_s: float = 0.8   # frame-to-frame palm speed below this is "at rest"
    rest_arm_ms: float = 180.0     # continuous rest that arms the recognizer (start, after reset / fire)
    vertical_min_travel_pu: float = 1.6
    vertical_rest_ms: float = 150.0   # a vertical swipe must start from at least this much rest


def open_palm(h: HandFeatures, min_open: int = 3) -> bool:
    """At least `min_open` of index, middle, ring, little EXTENDED (thumb ignored)."""
    s = {f.name: f.state for f in h.fingers}
    n = sum(s.get(n) is FingerState.EXTENDED
            for n in (FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE))
    return n >= min_open


def direction_of(dx_px: float, dy_px: float) -> SwipeDirection:
    """Dominant-axis direction of an image-space displacement, from the user's point of view."""
    if abs(dx_px) >= abs(dy_px):
        return SwipeDirection.LEFT if dx_px > 0 else SwipeDirection.RIGHT
    return SwipeDirection.UP if dy_px < 0 else SwipeDirection.DOWN


class SwipeRecognizer:
    def __init__(self, config: SwipeConfig = SwipeConfig()) -> None:
        self.cfg = config
        self._hist: deque[tuple[float, float, float]] = deque()   # (t, x px, y px)
        self._hand: Optional[int] = None
        self._last_fire: Optional[tuple[float, SwipeDirection]] = None
        self._prev: Optional[tuple[float, float, float]] = None   # last accepted sample (survives a fire)
        self._rest_since: Optional[float] = None     # start of the current still run
        self._armed_at: Optional[float] = None       # start of the rest that armed us; None = disarmed
        self._run: Optional[tuple[float, float]] = None   # (start, end) of the still run motion last left

    def reset(self) -> None:
        """Drop the motion history (tracking gap, ambiguity, pinch, mode change) and disarm: the
        next swipe needs the palm at rest first. The cooldown and the opposite-direction lock
        survive: a reset never makes a return stroke fire."""
        self._hist.clear()
        self._hand = None
        self._prev = None
        self._rest_since = None
        self._armed_at = None
        self._run = None

    def update(self, t_ms: float, hand: Optional[HandFeatures]) -> Optional[SwipeDirection]:
        """One frame of the dominant hand (None = not seen). Returns the swipe that fired, if any."""
        cfg = self.cfg
        if (hand is None or hand.quality is not Quality.USABLE or not hand.palm_scale_px > 0
                or not open_palm(hand, cfg.min_open_fingers)):
            self.reset()
            return None
        x, y = hand.palm_center_px
        if not (math.isfinite(x) and math.isfinite(y)):
            self.reset()
            return None
        if hand.hand_id != self._hand or (self._hist and t_ms - self._hist[-1][0] > cfg.max_gap_ms):
            self.reset()
        self._hand = hand.hand_id
        if self._hist and t_ms <= self._hist[-1][0]:
            return None   # duplicate / out-of-order frame
        self._track_rest(t_ms, x, y, hand.palm_scale_px)
        self._hist.append((t_ms, x, y))
        while self._hist and t_ms - self._hist[0][0] > cfg.max_window_ms:
            self._hist.popleft()
        hit = self._match(t_ms, hand.palm_scale_px)
        if hit is not None:
            self._last_fire = (t_ms, hit)
            self._hist.clear()
            self._armed_at = None    # every fire needs a fresh rest before the next one
            self._run = None
        return hit

    def _track_rest(self, t: float, x: float, y: float, scale: float) -> None:
        cfg = self.cfg
        p, self._prev = self._prev, (t, x, y)
        if p is None:
            return
        v = math.hypot(x - p[1], y - p[2]) / scale / ((t - p[0]) / 1000.0)
        if v < cfg.rest_speed_pu_s:
            if self._rest_since is None:
                self._rest_since = p[0]
            if self._armed_at is None and t - self._rest_since >= cfg.rest_arm_ms:
                self._armed_at = self._rest_since
        elif self._rest_since is not None:
            self._run = (self._rest_since, p[0])   # motion onset at p[0]
            self._rest_since = None

    def _blocked(self, start_t: float, d: SwipeDirection) -> bool:
        if self._armed_at is None or start_t < self._armed_at:
            return True
        if d in (SwipeDirection.UP, SwipeDirection.DOWN):
            # measured from inside the rest that the motion left: all motion since onset counts
            run = self._run
            if (run is None or run[1] - run[0] < self.cfg.vertical_rest_ms
                    or not run[0] <= start_t <= run[1]):
                return True
        lf = self._last_fire
        if lf is None:
            return False
        t_fire, prev = lf
        if start_t < t_fire + self.cfg.cooldown_ms:
            return True
        return d is _OPPOSITE[prev] and start_t < t_fire + self.cfg.opposite_lock_ms

    def _match(self, t_ms: float, scale: float) -> Optional[SwipeDirection]:
        cfg = self.cfg
        pts = list(self._hist)
        if len(pts) < 2:
            return None
        _, x1, y1 = pts[-1]
        # peak speed of each suffix, computed from the newest sample backwards
        peak = 0.0
        best: Optional[SwipeDirection] = None
        for i in range(len(pts) - 2, -1, -1):
            ta, xa, ya = pts[i]
            tb, xb, yb = pts[i + 1]
            if tb > ta:
                peak = max(peak, math.hypot(xb - xa, yb - ya) / scale / ((tb - ta) / 1000.0))
            dx, dy = x1 - xa, y1 - ya
            major, minor = max(abs(dx), abs(dy)), min(abs(dx), abs(dy))
            if major / scale < cfg.min_travel_pu or major < cfg.axis_ratio * minor:
                continue
            if peak < cfg.min_peak_speed_pu_s:
                continue
            d = direction_of(dx, dy)
            if abs(dy) > abs(dx) and major / scale < cfg.vertical_min_travel_pu:
                continue
            if self._blocked(ta, d):
                continue
            best = d
            break
        return best


# ---------------------------------------------------------------- profiles

PROFILES = ("slides", "browser", "media", "desktops")
DEFAULT_PROFILE = "desktops"

_HORIZONTAL = {
    "slides": (KeyCommand.NEXT, KeyCommand.PREVIOUS),
    "browser": (KeyCommand.BROWSER_FORWARD, KeyCommand.BROWSER_BACK),
    "media": (KeyCommand.MEDIA_NEXT, KeyCommand.MEDIA_PREVIOUS),
    "desktops": (KeyCommand.DESKTOP_RIGHT, KeyCommand.DESKTOP_LEFT),
}

_PROCESS_PROFILES = {
    "slides": ("powerpnt.exe", "soffice.bin", "acrord32.exe", "acrobat.exe", "sumatrapdf.exe",
               "foxitpdfreader.exe", "microsoft.photos.exe", "photos.exe"),
    "browser": ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe",
                "explorer.exe"),
    "media": ("spotify.exe", "vlc.exe", "wmplayer.exe", "music.ui.exe", "applemusic.exe", "mpc-hc64.exe"),
}
_BY_PROCESS = {name: prof for prof, names in _PROCESS_PROFILES.items() for name in names}

COMMAND_LABELS = {
    KeyCommand.NEXT: "Sonraki",
    KeyCommand.PREVIOUS: "Önceki",
    KeyCommand.BROWSER_BACK: "Geri",
    KeyCommand.BROWSER_FORWARD: "İleri",
    KeyCommand.TASK_VIEW: "Görev görünümü",
    KeyCommand.SHOW_DESKTOP: "Masaüstünü göster",
    KeyCommand.DESKTOP_LEFT: "Soldaki masaüstü",
    KeyCommand.DESKTOP_RIGHT: "Sağdaki masaüstü",
    KeyCommand.MEDIA_PLAY_PAUSE: "Oynat / duraklat",
    KeyCommand.MEDIA_NEXT: "Sonraki parça",
    KeyCommand.MEDIA_PREVIOUS: "Önceki parça",
    KeyCommand.VOLUME_MUTE: "Sesi kapat / aç",
}


def profile_for_process(name: Optional[str]) -> str:
    """Foreground process exe name (any case) -> profile; unknown or None -> "desktops"."""
    if not name:
        return DEFAULT_PROFILE
    return _BY_PROCESS.get(name.strip().lower().rsplit("\\", 1)[-1], DEFAULT_PROFILE)


def resolve_profile(setting: str, process_name: Optional[str]) -> str:
    """Settings value ("auto" or a profile) -> concrete profile."""
    if setting in PROFILES:
        return setting
    return profile_for_process(process_name)


def swipe_command(profile: str, direction: SwipeDirection) -> KeyCommand:
    if direction is SwipeDirection.UP:
        return KeyCommand.TASK_VIEW
    if direction is SwipeDirection.DOWN:
        return KeyCommand.SHOW_DESKTOP
    left, right = _HORIZONTAL.get(profile, _HORIZONTAL[DEFAULT_PROFILE])
    return left if direction is SwipeDirection.LEFT else right


def pinch_command(profile: str) -> KeyCommand:
    return KeyCommand.NEXT if profile == "slides" else KeyCommand.MEDIA_PLAY_PAUSE


__all__ = [
    "COMMAND_LABELS",
    "DEFAULT_PROFILE",
    "PROFILES",
    "SwipeConfig",
    "SwipeDirection",
    "SwipeRecognizer",
    "direction_of",
    "open_palm",
    "pinch_command",
    "profile_for_process",
    "resolve_profile",
    "swipe_command",
]
