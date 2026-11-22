"""Instrument mode (round 7): virtual guitar strings between the hands, real-time plucked-string audio.

geometry/strings/music/engine/session: stdlib + contracts only (tracking thread, deterministic).
synth (numpy) and audio (sounddevice) are imported lazily by the app, never by the pure modules.
"""
from __future__ import annotations
