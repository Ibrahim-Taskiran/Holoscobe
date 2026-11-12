from __future__ import annotations

from handcontrol.app import STATUS_HINT_TR, settings_to_dialog_data
from handcontrol.config import validate


def test_settings_dialog_receives_every_stored_value() -> None:
    s = validate({'scroll_direction': 'reversed', 'zoom_direction': 'reversed', 'overlay_visible': False,
                  'mascot_visible': False, 'camera': {'backend': 'dshow', 'index': 2},
                  'monitor_mapping': {'mode': 'monitor', 'monitor_index': 1}, 'start_with_windows': True})
    d = settings_to_dialog_data(s)
    assert (d.scroll_direction, d.zoom_direction) == ('reverse', 'reverse')
    assert (d.show_overlay, d.show_mascot, d.start_with_windows) == (False, False, True)
    assert (d.camera_backend, d.camera_index, d.monitor_mapping) == ('directshow', 2, 'secondary')


def test_settings_dialog_defaults_round_trip() -> None:
    d = settings_to_dialog_data(validate({}))
    assert (d.scroll_direction, d.zoom_direction, d.camera_backend) == ('natural', 'natural', 'media_foundation')
    assert d.monitor_mapping == 'primary'


def test_status_hint_describes_pinch_clicks() -> None:
    assert 'pinch' in STATUS_HINT_TR and 'sağ tık' in STATUS_HINT_TR
    assert 'öne/geri' not in STATUS_HINT_TR
