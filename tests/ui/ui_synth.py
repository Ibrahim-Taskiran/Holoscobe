"""Synthetic hands for the UI tests."""
from __future__ import annotations

import math
from typing import Optional

from handcontrol.contracts import (
    FingerInfo, FingerName, FingerState, FrameFeatures, Handedness, HandFeatures, Landmark, Quality,
)


def build_synthetic_hand(
    hand_id: int = 1,
    handedness: Handedness = Handedness.RIGHT,
    quality: Quality = Quality.USABLE,
    center_x: float = 0.35,
    center_y: float = 0.55,
    phase: float = 0.0,
    uncertain_finger: Optional[FingerName] = None,
) -> HandFeatures:
    """Create a synthetic 21-landmark HandFeatures instance for demos and tests."""
    # 21 landmarks: 0 wrist, 1-4 thumb, 5-8 index, 9-12 middle, 13-16 ring, 17-20 little
    sign = -1.0 if handedness == Handedness.LEFT else 1.0
    wrist_x = center_x + 0.03 * math.sin(phase)
    wrist_y = center_y + 0.02 * math.cos(phase)

    landmarks: list[Landmark] = [Landmark(x=wrist_x, y=wrist_y, z=0.0)]

    finger_offsets = [
        (-0.09 * sign, -0.04),  # Thumb
        (-0.04 * sign, -0.11),  # Index
        (0.00 * sign, -0.12),   # Middle
        (0.04 * sign, -0.11),   # Ring
        (0.08 * sign, -0.09),   # Little
    ]

    for f_idx, (dx, dy) in enumerate(finger_offsets):
        curl_wave = 0.5 + 0.4 * math.sin(phase + f_idx * 0.7)
        for joint in range(1, 5):
            scale = joint * (0.28 - 0.08 * curl_wave)
            lx = max(0.02, min(0.98, wrist_x + dx * scale * 1.4))
            ly = max(0.02, min(0.98, wrist_y + dy * scale * 1.4))
            landmarks.append(Landmark(x=lx, y=ly, z=-0.01 * joint))

    fingers: list[FingerInfo] = []
    for f_idx, f_name in enumerate(FingerName):
        curl_val = round(max(0.0, min(1.0, 0.45 + 0.45 * math.sin(phase + f_idx))), 2)
        if f_name == uncertain_finger or quality == Quality.UNKNOWN:
            state = FingerState.UNKNOWN
        elif curl_val < 0.45:
            state = FingerState.EXTENDED
        else:
            state = FingerState.BENT
        fingers.append(FingerInfo(name=f_name, state=state, curl=curl_val))

    width_px, height_px = 640.0, 480.0
    palm_cx = wrist_x * width_px
    palm_cy = (wrist_y - 0.06) * height_px
    index_tip = landmarks[8]
    thumb_tip = landmarks[4]
    pinch_px = math.hypot(
        (index_tip.x - thumb_tip.x) * width_px,
        (index_tip.y - thumb_tip.y) * height_px,
    )
    palm_scale = 85.0

    return HandFeatures(
        hand_id=hand_id,
        handedness=handedness,
        quality=quality,
        palm_center_px=(palm_cx, palm_cy),
        palm_scale_px=palm_scale,
        fingers=tuple(fingers),
        pinch_distance=round(pinch_px / palm_scale, 3),
        index_tip_px=(index_tip.x * width_px, index_tip.y * height_px),
        landmarks=tuple(landmarks),
    )


def build_synthetic_frame(
    hand_count: int = 2,
    phase: float = 0.0,
    uncertain: bool = False,
    capture_ms: float = 1000.0,
    inference_done_ms: float = 1014.5,
) -> FrameFeatures:
    """Create a synthetic FrameFeatures with 0, 1, or 2 hands."""
    hands: list[HandFeatures] = []
    if hand_count >= 1:
        hands.append(
            build_synthetic_hand(
                hand_id=1,
                handedness=Handedness.RIGHT,
                quality=Quality.DEGRADED if uncertain else Quality.USABLE,
                center_x=0.34,
                center_y=0.62,
                phase=phase,
                uncertain_finger=FingerName.RING if uncertain else None,
            )
        )
    if hand_count >= 2:
        hands.append(
            build_synthetic_hand(
                hand_id=2,
                handedness=Handedness.LEFT,
                quality=Quality.USABLE,
                center_x=0.68,
                center_y=0.62,
                phase=phase + 1.2,
                uncertain_finger=FingerName.LITTLE if uncertain else None,
            )
        )
    return FrameFeatures(
        capture_ms=capture_ms,
        inference_done_ms=inference_done_ms,
        width=640,
        height=480,
        hands=tuple(hands),
        identity_ambiguous=uncertain,
    )
