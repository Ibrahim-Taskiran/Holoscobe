# Holoscobe — PySide6 Arayüz (UI) Raporu

## 1. Yazılan Dosyalar
- `src/handcontrol/ui/__init__.py`
- `src/handcontrol/ui/viewmodel.py`
- `src/handcontrol/ui/tray.py`
- `src/handcontrol/ui/preview.py`
- `src/handcontrol/ui/calibration.py`
- `src/handcontrol/ui/settings.py`
- `src/handcontrol/ui/overlay.py`
- `src/handcontrol/ui/feedback.py`
- `src/handcontrol/ui/demo.py`
- `tests/ui/conftest.py`
- `tests/ui/test_ui_components.py`

## 2. Test Durumu
- Komut: `.venv\Scripts\python.exe -m pytest tests\ui -q`
- Toplam: 11 test (10 otomatik + 1 `@pytest.mark.manual`)
- Geçen: 10
- Kalan / Başarısız: 0 (`1 deselected` — `@pytest.mark.manual` varsayılan olarak atlanır)

## 3. `ui/viewmodel.py` Sınıf ve Sinyal Adları
- **Veri Sınıfları ve Enum'lar:**
  - `TrayIconState` (`PAUSED`, `ACTIVE`, `CALIBRATING`, `CAMERA_UNAVAILABLE`)
  - `OverlayMenuKind` (`NONE`, `MODE_MENU`, `WINDOW_ACTION_MENU`)
  - `WindowActionKind` (`MINIMIZE`, `MAXIMIZE_RESTORE`, `MOVE_OTHER_MONITOR`, `CLOSE`)
  - `FeedbackKind` (`ACTIVATED`, `PAUSED`, `MODE_CHANGED`, `VOLUME`, `CLOSE_CONFIRM`, `INFO`, `WARNING`)
  - `VirtualCursorState` (`x`, `y`, `visible`, `pinching`, `hold_progress`)
  - `OverlayMenuItem` (`item_id`, `label`, `enabled`, `active`, `hovered`, `armed`, `hold_progress`)
  - `OverlayState` (`visible`, `kind`, `title`, `items`, `cursor`, `inactivity_ms`, `timeout_ms`, `closing_progress`, `target_window_title`)
  - `FeedbackMessage` (`kind`, `text`, `volume_percent`, `hold_progress`, `duration_ms`)
  - `UiState` (`control_state`, `camera_state`, `mode`, `menu_items`, `virtual_cursor`, `hold_progress`, `fps`, `sample_age_ms`, `error_text`, `mirrored`, `dry_run`, `dry_run_command_text`, `overlay`, `latest_frame`)
- **`UiBridge(QObject)` Durum Bildirim Sinyalleri (Arayüz bileşenleri dinler):**
  - `state_changed(UiState)`
  - `frame_updated(Optional[FrameFeatures])`
  - `overlay_updated(OverlayState)`
  - `feedback_triggered(FeedbackMessage)`
  - `dry_run_updated(str)`
- **`UiBridge(QObject)` Kullanıcı İsteği Sinyalleri (Yönetici / Denetleyici dinler):**
  - `pause_resume_requested()`
  - `pause_requested()`
  - `resume_requested()`
  - `camera_toggle_requested()`
  - `camera_start_requested()`
  - `camera_stop_requested()`
  - `settings_requested()`
  - `calibration_requested()`
  - `exit_requested()`
  - `mode_selected(Mode)`
  - `window_action_selected(str)`
  - `settings_saved(SettingsData)`
  - `calibration_completed(CalibrationResult)`
  - `calibration_cancelled()`
- **`UiBridge(QObject)` Durum Güncelleme Slotları (İş parçacığı güvenli):**
  - `update_state(new_state: UiState)`
  - `update_status(...)`
  - `update_frame(frame: Optional[FrameFeatures], fps: Optional[float], sample_age_ms: Optional[float])`
  - `update_overlay(overlay: OverlayState)`
  - `update_virtual_cursor(x: float, y: float, visible: bool, pinching: bool, hold_progress: float)`
  - `show_feedback(...)`
  - `record_dry_run_action(action: Action | str)`

## 4. Bekleyen İşler
- Yönetici (`app.py`) tarafından `UiBridge` sinyallerinin kamera, özellik çıkarımı, jest, denetleyici, ayar saklama (`config.py`) ve Windows bağdaştırıcılarına bağlanması (`bekliyor`).
- Gerçek kamera, gerçek el ve çift monitör ile donanım doğrulaması (`bekliyor`).
