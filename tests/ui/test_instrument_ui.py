"""Enstrüman UI: spark particles, instrument window, settings tab, tray and mode labels (round 7)."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from handcontrol.contracts import Mode
from handcontrol.instrument.events import (
    CHORD_NAMES,
    DEFAULT_CHORDS,
    SCALE_NAMES,
    HitView,
    InstrumentView,
    StringView,
)
from handcontrol.ui import InstrumentWindow, SparkSystem
from handcontrol.ui.demo import build_synthetic_frame
from handcontrol.ui.instrument_view import INSTRUMENT_WINDOW_TITLE_TR
from handcontrol.ui.overlay import build_mode_overlay_state
from handcontrol.ui.settings import INSTRUMENT_SCALE_LABELS_TR, SettingsData, SettingsDialog
from handcontrol.ui.tray import HandControlTray, create_mode_pixmap
from handcontrol.ui.viewmodel import MODE_LABELS_TR, UiBridge, UiState, create_mode_menu_items

W, H = 640, 480


class FakeClock:
    def __init__(self, t: float = 10_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _hit(x: float = 320.0, y: float = 240.0, velocity: float = 1.0, direction: int = 1) -> HitView:
    return HitView(string=0, x=x, y=y, velocity=velocity, direction=direction, t_ms=0.0)


def _frame_tips() -> tuple[tuple[float, float], tuple[float, float]]:
    frame = build_synthetic_frame(hand_count=2)
    a = frame.hands[0].landmarks[4]
    b = frame.hands[1].landmarks[8]
    return (a.x * W, a.y * H), (b.x * W, b.y * H)


def _solo_view(amplitude: float = 0.8, hits: tuple[HitView, ...] = ()) -> InstrumentView:
    p0, p1 = _frame_tips()
    return InstrumentView(
        t_ms=1000.0, width=W, height=H, layout="solo",
        strings=(StringView(0, p0, p1, amplitude, "A3", True),),
        hits=hits, note_label="A3 +0.7", chord_label="", playing=True, status="Çalıyor",
        pick_tip=((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2 - 30.0),
    )


def _chord_view(hits: tuple[HitView, ...] = ()) -> InstrumentView:
    p0, p1 = _frame_tips()
    strings = tuple(
        StringView(i, (p0[0], p0[1] - 45 + 30 * i), (p1[0], p1[1] - 45 + 30 * i),
                   (0.9, 0.6, 0.3, 0.0)[i], ("E2", "B2", "E3", "G3")[i], i != 3)
        for i in range(4)
    )
    return InstrumentView(
        t_ms=1000.0, width=W, height=H, layout="chord", strings=strings, hits=hits,
        note_label="", chord_label="Em", playing=True, status="Akor: Em",
    )


# ---------- SparkSystem ----------

def test_spark_count_scales_with_velocity_and_cap_holds() -> None:
    sparks = SparkSystem(seed=1, max_particles=50)
    assert sparks.count_for(0.0) < sparks.count_for(0.5) < sparks.count_for(1.0)
    assert sparks.emit(_hit(velocity=0.1), 0.0) < SparkSystem(seed=1).emit(_hit(velocity=1.0), 0.0)
    for _ in range(20):
        sparks.emit(_hit(velocity=1.0), 0.0)
    assert len(sparks) == 50


def test_spark_lifetime_and_gravity() -> None:
    sparks = SparkSystem(seed=2)
    sparks.emit(_hit(velocity=0.5, direction=-1), 0.0)
    assert all(250.0 <= p.life_ms <= 500.0 for p in sparks.particles)
    y0 = sum(p.vy for p in sparks.particles)
    sparks.step(50.0)
    assert len(sparks) > 0
    assert sum(p.vy for p in sparks.particles) > y0       # gravity pulls down (+y)
    sparks.step(200.0)
    sparks.step(400.0)
    sparks.step(520.0)
    assert len(sparks) == 0


def test_spark_system_is_deterministic_for_a_seed() -> None:
    def run(seed: int) -> list[tuple[float, float]]:
        s = SparkSystem(seed=seed)
        s.emit(_hit(), 0.0)
        s.step(16.0)
        s.step(33.0)
        return [(round(p.x, 6), round(p.y, 6)) for p in s.particles]

    assert run(7) == run(7)
    assert run(7) != run(8)


# ---------- InstrumentWindow ----------

def test_instrument_window_title_and_close_signal() -> None:
    win = InstrumentWindow(clock=FakeClock())
    assert win.windowTitle() == INSTRUMENT_WINDOW_TITLE_TR == "Holoscobe — Enstrüman"
    closed: list[bool] = []
    win.closed.connect(lambda: closed.append(True))
    win.show()
    win.close()
    assert closed == [True]
    assert not win.is_animating


def test_instrument_window_renders_solo_and_chord_with_hud() -> None:
    win = InstrumentWindow(clock=FakeClock())
    img_empty = win.render_to_image(W, H)
    assert not img_empty.isNull()
    assert win.hud_lines()[1] == "Düzen: —"

    win.update_view(_solo_view())
    img = win.render_to_image(W, H)
    assert not img.isNull()
    assert win.hud_lines() == ("A3 +0.7", "Düzen: Solo", "Çalıyor")

    win.update_view(_chord_view())
    win.render_to_image(W, H)
    assert win.hud_lines() == ("Em", "Düzen: Akor", "Akor: Em")


def test_mirror_flips_string_x_positions() -> None:
    win = InstrumentWindow(clock=FakeClock())
    win.update_view(_solo_view())
    win.render_to_image(W, H)
    canvas_rect = win.canvas.canvas_rect_for(win.canvas.rect().toRectF())
    s = win.view.strings[0]
    win.set_mirrored(False)
    a_plain, _ = win.canvas.string_points(s, canvas_rect)
    win.set_mirrored(True)
    assert win.mirrored
    a_mirror, _ = win.canvas.string_points(s, canvas_rect)
    assert abs(a_plain.x() - a_mirror.x()) > 1.0
    mid = canvas_rect.left() + canvas_rect.width() / 2
    assert abs((a_plain.x() - mid) + (a_mirror.x() - mid)) < 1e-6
    assert a_plain.y() == a_mirror.y()


def test_mirror_follows_bridge_state() -> None:
    bridge = UiBridge(UiState(mirrored=False))
    win = InstrumentWindow(bridge=bridge, clock=FakeClock())
    assert win.mirrored is False
    bridge.update_status(mirrored=True)
    assert win.mirrored is True


def test_sounding_string_changes_pixels_vs_still_string() -> None:
    clock = FakeClock()
    win = InstrumentWindow(clock=clock)
    win.update_view(_solo_view(amplitude=0.0))
    still = win.render_to_image(W, H)
    clock.t += 37.0
    win.update_view(_solo_view(amplitude=1.0))
    waving = win.render_to_image(W, H)
    assert still != waving


def test_particles_toggle() -> None:
    clock = FakeClock()
    win = InstrumentWindow(clock=clock)
    win.update_view(_solo_view(hits=(_hit(velocity=0.9),)))
    assert len(win.sparks) > 0
    win.set_particles_enabled(False)
    assert not win.particles_enabled
    assert len(win.sparks) == 0
    win.update_view(_solo_view(hits=(_hit(velocity=0.9),)))
    assert len(win.sparks) == 0
    win.set_particles_enabled(True)
    win.update_view(_solo_view(hits=(_hit(velocity=0.9),)))
    assert len(win.sparks) > 0


def test_timer_runs_only_while_visible() -> None:
    win = InstrumentWindow(clock=FakeClock())
    assert not win.is_animating
    win.show()
    assert win.is_animating
    win.hide()
    assert not win.is_animating
    win.show()
    assert win.is_animating
    win.close()
    assert not win.is_animating


def test_save_instrument_screenshots() -> None:
    out_dir = Path(os.environ.get(
        "HOLOSCOBE_SCREENSHOT_DIR",
        r"C:\Users\ibrah\AppData\Local\Temp\claude\23567fb5f2fc9f49\415b4c6d-8a33-4f51-abe6-ceffd247dcb3\scratchpad",
    ))
    if not out_dir.is_dir():
        out_dir = Path(os.environ.get("TEMP", "."))
    camera = QImage(W, H, QImage.Format.Format_RGB32)
    camera.fill(QColor(40, 46, 58))
    frame = build_synthetic_frame(hand_count=2)

    clock = FakeClock()
    win = InstrumentWindow(clock=clock)
    win.set_camera_image(camera)
    win.set_frame(frame)
    win.update_view(_solo_view(amplitude=0.9))
    clock.t += 20.0
    assert win.render_to_image(960, 620).save(str(out_dir / "instrument_solo.png"))

    p0, p1 = _frame_tips()
    hits = tuple(_hit(x=p0[0] + (p1[0] - p0[0]) * 0.5, y=p0[1] - 45 + 30 * i + (p1[1] - p0[1]) * 0.5,
                      velocity=0.9 - 0.2 * i) for i in range(3))
    win.update_view(_chord_view(hits=hits))
    clock.t += 60.0
    assert win.render_to_image(960, 620).save(str(out_dir / "instrument_chord_sparks.png"))


# ---------- settings tab ----------

def _tab_index(dlg: SettingsDialog, text: str) -> int:
    for i in range(dlg.tabs.count()):
        if dlg.tabs.tabText(i) == text:
            return i
    return -1


def test_settings_instrument_tab_labels() -> None:
    dlg = SettingsDialog()
    assert _tab_index(dlg, "Enstrüman") >= 0
    assert [dlg.combo_instrument_layout.itemText(i) for i in range(2)] == ["Solo", "Akor"]
    assert dlg.combo_instrument_scale.count() == len(SCALE_NAMES)
    assert set(INSTRUMENT_SCALE_LABELS_TR) == set(SCALE_NAMES)
    assert dlg.combo_instrument_scale.itemText(0) == "Mi minör pentatonik"
    assert dlg.chk_instrument_quantize.text() == "Diziye kilitle"
    assert len(dlg.combo_chords) == 4
    assert all(c.count() == len(CHORD_NAMES) for c in dlg.combo_chords)
    assert [dlg.combo_instrument_tone.itemText(i) for i in range(2)] == ["Temiz", "Elektro"]
    assert [dlg.combo_audio_latency.itemText(i) for i in range(2)] == ["Düşük", "Normal"]
    assert dlg.combo_audio_device.itemText(0) == "Sistem varsayılanı"
    assert dlg.chk_instrument_particles.text() == "Kıvılcım efektleri"
    assert dlg.btn_test_sound.text() == "Test sesi çal"
    defaults = dlg.get_settings()
    assert defaults.instrument_chords == DEFAULT_CHORDS
    assert defaults.instrument_volume == 0.5
    assert dlg.label_instrument_volume.text() == "%50"


def test_settings_instrument_round_trip_and_reset() -> None:
    custom = SettingsData(
        instrument_layout="chord", instrument_scale="d_dorian", instrument_quantize=False,
        instrument_chords=("Am", "F", "C", "G7"), instrument_volume=0.8, instrument_tone="electric",
        audio_device="Hoparlör (Realtek)", audio_latency="normal", instrument_particles=False,
        audio_device_choices=("Hoparlör (Realtek)", "Kulaklık (USB)"),
    )
    dlg = SettingsDialog(initial=custom)
    out = dlg.get_settings()
    assert out == custom
    assert SettingsData.from_dict(out.to_dict()) == custom
    # Settings stores lists for chords: accepted and normalized to a tuple.
    assert SettingsData.from_dict({"instrument_chords": ["Am", "Bogus"]}).instrument_chords == (
        "Am", DEFAULT_CHORDS[1], DEFAULT_CHORDS[2], DEFAULT_CHORDS[3])

    dlg.reset_to_defaults()
    reset = dlg.get_settings()
    assert reset.instrument_layout == "free"
    assert reset.instrument_scale == "e_minor_pentatonic"
    assert reset.instrument_quantize is True
    assert reset.instrument_chords == DEFAULT_CHORDS
    assert reset.audio_device == ""
    assert reset.instrument_particles is True
    assert dlg.combo_audio_device.count() == 3     # default + 2 devices still listed


def test_settings_unknown_device_kept_and_test_sound_signal() -> None:
    dlg = SettingsDialog(initial=SettingsData(audio_device="Eski Cihaz", audio_device_choices=("Kulaklık (USB)",)))
    assert dlg.combo_audio_device.count() == 3
    assert dlg.get_settings().audio_device == "Eski Cihaz"
    got: list[str] = []
    dlg.test_sound_requested.connect(got.append)
    dlg.btn_test_sound.click()
    dlg.combo_audio_device.setCurrentIndex(dlg.combo_audio_device.findData("Kulaklık (USB)"))
    dlg.btn_test_sound.click()
    dlg.combo_audio_device.setCurrentIndex(0)
    dlg.btn_test_sound.click()
    assert got == ["Eski Cihaz", "Kulaklık (USB)", ""]


def test_settings_default_mode_combo_has_instrument() -> None:
    dlg = SettingsDialog(initial=SettingsData(default_mode="instrument"))
    assert dlg.combo_mode.findData("instrument") >= 0
    assert dlg.combo_mode.itemText(dlg.combo_mode.findData("instrument")) == "Enstrüman"
    assert dlg.get_settings().default_mode == "instrument"


# ---------- tray, labels, overlay ----------

def test_mode_labels_and_icon_for_instrument() -> None:
    assert MODE_LABELS_TR[Mode.INSTRUMENT] == "Enstrüman"
    assert set(MODE_LABELS_TR) == set(Mode)
    pix = create_mode_pixmap(Mode.INSTRUMENT, 32)
    assert not pix.isNull()
    assert pix.toImage() != create_mode_pixmap(Mode.COMMANDS, 32).toImage()
    items = create_mode_menu_items(active_mode=Mode.INSTRUMENT)
    assert [i.label for i in items if i.active] == ["Enstrüman"]
    assert any(i.item_id == "instrument" for i in build_mode_overlay_state(active_mode=Mode.INSTRUMENT).items)
    assert UiState(mode=Mode.INSTRUMENT).mode_label_tr == "Enstrüman"


def test_tray_instrument_mode_action_and_window_action() -> None:
    bridge = UiBridge()
    tray = HandControlTray(bridge)
    act = tray.mode_actions[Mode.INSTRUMENT]
    assert act.text() == "Enstrüman"
    selected: list[Mode] = []
    bridge.mode_selected.connect(selected.append)
    act.trigger()
    assert selected == [Mode.INSTRUMENT]

    requested: list[bool] = []
    bridge.instrument_window_requested.connect(lambda: requested.append(True))
    assert tray.action_instrument_window.text() == "Enstrüman penceresi"
    assert tray.action_instrument_window in tray.menu.actions()
    tray.action_instrument_window.trigger()
    assert requested == [True]
