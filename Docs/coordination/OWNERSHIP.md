# Holoscobe — dosya sahipliği ve ortak kurallar

Üç yapay zekâ aynı klasörde aynı anda çalışıyor: Claude (yönetici + alt ajanlar), Codex, Antigravity.
Bu dosya bağlayıcıdır. Yalnız Claude yöneticisi günceller.

## Sahiplik (yalnız kendi satırındaki yollara yaz)

| Sahip | Yazabileceği yollar |
|---|---|
| Claude yönetici | `src/handcontrol/contracts.py`, `src/handcontrol/__init__.py`, `src/handcontrol/app.py`, `Docs/coordination/OWNERSHIP.md`, `.gitignore`, `README.md` |
| Claude A (temel) | `pyproject.toml`, `requirements*.txt`, `assets/**`, `scripts/**`, `THIRD_PARTY_NOTICES.md`, `Docs/reports/phase0_*` |
| Claude B (özellikler) | `src/handcontrol/features.py`, `src/handcontrol/filters.py`, `tests/features/**` |
| Claude C (jestler) | `src/handcontrol/gestures.py`, `tests/gestures/**` |
| Claude D (denetleyici) | `src/handcontrol/controller.py`, `src/handcontrol/mapping.py`, `src/handcontrol/safety.py`, `src/handcontrol/dryrun.py`, `tests/controller/**` |
| Claude E (kamera) | `src/handcontrol/camera.py`, `src/handcontrol/tracking.py`, `src/handcontrol/config.py`, `tests/camera/**`, `tests/config/**` |
| Codex | `src/handcontrol/windows/**`, `tests/windows/**`, `Docs/reports/windows_*` |
| Antigravity | `src/handcontrol/ui/**`, `tests/ui/**`, `Docs/reports/ui_*` |

Herkes kendi istek dosyasını yazabilir: `Docs/coordination/REQUESTS_<ad>.md`.

## Kurallar

1. Sahibi olmadığın dosyayı yazma, silme, taşıma, yeniden biçimlendirme. Okumak serbest.
2. `contracts.py` dondurulmuştur. Değişiklik ya da yeni paket gerekirse `REQUESTS_<ad>.md` dosyasına yaz, yerelde çalışmaya devam et.
3. Git'e yazan komut yasak: `commit`, `add`, `stash`, `reset`, `checkout`, `clean`, `rebase`. Yalnız `git status` ve `git diff` serbest. Commit'i Claude yöneticisi atar.
4. Paket kurma yalnız Claude A'da. Diğerleri `.venv` içine paket kurmaz. İstisna: sahibi olduğun alanın paketi A tarafından henüz kurulmadıysa bekleme, isteğini yaz ve kodu yaz.
5. Ortak `tests/conftest.py` yok. Her sahip kendi test klasöründe kendi `conftest.py` dosyasını tutar.
6. Test komutu: `.venv\Scripts\python.exe -m pytest tests\<klasörün> -q`. Tam takımı yalnız yönetici çalıştırır.
7. Ekranda pencere açan, fareyi/klavyeyi oynatan, sesi değiştiren, pencere kapatan test otomatik çalışmaz. Bunlar `@pytest.mark.manual` ile işaretlenir ve varsayılan olarak atlanır.
8. Donanım doğrulaması (kamera, gerçek el, iki monitör) sahte veriyle "geçti" yazılmaz. Durum: `bekliyor`.
9. Ücretli araç, API anahtarı, bulut servisi, deneme sürümü yok.
10. Kod ve yorumlar İngilizce. Kullanıcıya görünen arayüz metinleri Türkçe.
11. Python 3.11, tip ipuçları, `from __future__ import annotations`. `features.py`, `filters.py`, `gestures.py`, `controller.py`, `safety.py` yalnız stdlib + `contracts` içe aktarır.

## Belgeler

- Şartname: `Docs/Windows_Hand_Gesture_Control_Spec.md` (154 satır, bölüm numaraları §1–§10)
- Yol haritası: `Docs/ROADMAP_TR.md`
- Sözleşmeler: `src/handcontrol/contracts.py`

## Ek sahiplik (2. tur, 2026-11-12)

| Sahip | Yazabileceği yollar |
|---|---|
| Claude F (birleştirme) | `src/handcontrol/pipeline.py`, `tests/integration/**`; ayrıca birleştirme hatası için Claude A–E dosyalarında en küçük düzeltme |
| Claude G (kabul araçları) | `src/handcontrol/tools/**`, `tests/tools/**` |

`windows/**`, `ui/**` ve `contracts.py` bu turda da yalnız kendi sahiplerinindir.

## Yönetici devri (2026-11-12)

Kullanıcı talimatıyla Claude yönetici hakları Codex'e devredildi. Codex uygulama girişini,
pipeline/test entegrasyonunu ve teslim belgelerini tamamlayabilir; gerekli en küçük Claude
modülü düzeltmelerini yapabilir, conventional commit oluşturabilir ve main'e push edebilir.
Paket kurulmaz. UI yalnız zorunlu bağlama düzeltmesiyle değiştirilir. Donanım kapıları insan
doğrulamasına kadar bekliyor kalır.

## 3. tur — tıklama eylemleri (2026-11-12)

"Yönetici devri" bölümü geçersizdir: yönetici yeniden Claude'dur. Commit'i yalnız Claude yöneticisi atar.
Bu turda Antigravity yok; `ui/**` geçici olarak Claude alt ajanındadır.

| Sahip | Yazabileceği yollar |
|---|---|
| Codex | `src/handcontrol/windows/**`, `tests/windows/**`, `Docs/reports/windows_*`, `Docs/coordination/REQUESTS_codex.md` |
| Claude H (jest + denetleyici) | `features.py`, `filters.py`, `gestures.py`, `index_tap.py`, `controller.py`, `safety.py`, `dryrun.py`, `pipeline.py`, `tests/features/**`, `tests/gestures/**`, `tests/controller/**`, `tests/integration/**` |
| Claude I (arayüz + belgeler) | `src/handcontrol/ui/**`, `tests/ui/**`, `app.py`, `tests/app/**`, `README.md`, `Docs/reports/*` (`windows_*` hariç) |

Sözleşme istisnası: `contracts.py` içinde `ActionKind`'a yalnız şu dört üye eklenir (`LEFT_CLICK` satırının altına).
İlk gelen ekler, sonraki dokunmaz. Başka hiçbir sözleşme değişikliği yapılmaz.

```python
    RIGHT_CLICK = "right_click"                     # x, y
    DOUBLE_CLICK = "double_click"                   # x, y
    LEFT_DOWN = "left_down"                         # x, y; left button held (drag start)
    LEFT_UP = "left_up"                             # x, y; left button released (drag end)
```

### 3. tur ek — Codex ikinci görev (2026-11-12)

Codex'e ek yollar: `src/handcontrol/windows/startup.py` (yeni), `scripts/build.ps1` (yeni), `packaging/**` (yeni),
`Docs/reports/windows_startup_packaging.md`. `app.py` ve `ui/**` bağlaması Claude tarafındadır; Codex dokunmaz.

## 4. tur — göreli imleç, debriyaj, tıklama iyileştirme (2026-11-12)

Kullanıcı kamera denemesi: tek sol tık zor, ikinci ekrana geçilemiyor, el çok geniş hareket etmeli, sağ tık kararsız.

| Sahip | Yazabileceği yollar |
|---|---|
| Claude H (imleç + tıklama) | `controller.py`, `mapping.py`, `filters.py`, `features.py`, `gestures.py`, `middle_pinch.py`, `index_tap.py`, `dryrun.py`, `safety.py`, `config.py`, `pipeline.py`, `src/handcontrol/` altında yeni stdlib modülleri, `tests/controller/**`, `tests/integration/**`, `tests/features/**`, `tests/gestures/**`, `tests/config/**` |
| Codex (ölçüm araçları) | `src/handcontrol/tools/click_record.py` (yeni), `src/handcontrol/tools/pointer_probe.py` (yeni), `tests/tools/test_tools_click_record.py`, `tests/tools/test_tools_pointer_probe.py` (yeni), `scripts/click_record.ps1`, `scripts/pointer_probe.ps1` (yeni), `Docs/reports/windows_measure_tools.md`, `Docs/coordination/REQUESTS_codex.md` |
| Claude I (arayüz, H bitince) | `src/handcontrol/ui/**`, `tests/ui/**`, `app.py`, `tests/app/**`, `README.md`, `Docs/reports/*` (`windows_*` hariç) |

`contracts.py` bu turda değişmez. `Pipeline`, `DryRunSink` ve `tools/common.py` genel adları yeniden adlandırılmaz (Codex aracı bunlara bağlı).

## Geçici devir — Claude kotası (2026-11-12)

Claude kotası bittiği sürece Codex, 4. turdaki Claude H işini (tıklama kararı, sektirme, takip kopması, kayıt tekrar testi)
tamamlayabilir: Claude H yollarına yazabilir, tam test takımını çalıştırabilir, conventional commit atabilir. Push yok.
`contracts.py` değişmez, paket kurulmaz. Claude döndüğünde yönetim yine Claude'dadır.

## 5. tur — kontrol kolaylığı (2026-11-14)

Kullanıcı: bazı hareketler hâlâ zor, kontrol kolay değil. Yönetici Claude (Fable); kod yazmaz. Bu turda Codex ve Antigravity yok.
"Geçici devir — Claude kotası" bölümü geçersizdir.

| Sahip | Yazabileceği yollar |
|---|---|
| Claude J (denetleyici, Opus) | `controller.py`, `tests/controller/**`, `tests/integration/**` |
| Claude K (kamera + takip, Sonnet) | `camera.py`, `tracking.py`, `tests/camera/**` |
| Claude L (telemetri, Sonnet) | `src/handcontrol/telemetry.py` (yeni), `src/handcontrol/tools/session_report.py` (yeni), `tests/tools/test_tools_session_report.py` (yeni), `tests/app/test_telemetry.py` (yeni), `app.py`, `pipeline.py`, `Docs/reports/telemetry.md` |
| Claude M (arayüz geri bildirimi, Sonnet) | `src/handcontrol/ui/**`, `tests/ui/**`, `Docs/reports/ui_feedback_round5.md` |
| Claude N (kayıt analizi, Haiku) | yalnız `Docs/reports/hw_click_reanalysis.md` (yeni); depo kodu yazmaz |

`contracts.py`, `config.py`, `features.py`, `filters.py`, `gestures.py` bu turda değişmez.
Ortak sözleşme: `ControllerSnapshot` (controller.py) sonuna varsayılanlı üç alan eklenir, yalnız J ekler:
`pointer_engaged: bool = False`, `tracking_ok: bool = True`, `last_cancel: str = ""`.
L ve M bu alanları `getattr(snap, "<ad>", <varsayılan>)` ile okur; J bitmeden de çalışır.
Ek: Claude K ayrıca `src/handcontrol/tools/profile_compare.py` dosyasına yazabilir.

## 6. tur — final sürüm (2026-11-18)

Kullanıcı: projeyi araştırma ve muadillere göre final hâline getir. Yönetici Claude (Opus 5.5); kod yazmaz, yalnız
`contracts.py` ve `config.py` şema 3 temelini kendisi yazdı. Bu turda Codex ve Antigravity yok.

| Sahip | Yazabileceği yollar |
|---|---|
| Claude P (denetleyici) | `controller.py`, `gestures.py`, `pipeline.py`, `src/handcontrol/swipe.py` (yeni), `src/handcontrol/dwell.py` (yeni), `tests/controller/**`, `tests/gestures/**`, `tests/integration/**` |
| Claude Q (Windows) | `src/handcontrol/windows/**`, `tests/windows/**`, `src/handcontrol/dryrun.py` |
| Claude R (arayüz) | `src/handcontrol/ui/**`, `tests/ui/**` |
| Claude S (uygulama + tanılama) | `app.py`, `tests/app/**`, `src/handcontrol/diagnostics.py` (yeni), `src/handcontrol/logsetup.py` (yeni), `src/handcontrol/telemetry.py` |

Sözleşme (yönetici yazdı): `Mode.COMMANDS`, `KeyCommand`, `ActionKind.KEY_COMMAND`, `Action.command`, `ProcessNames`.
Ayarlar şema 3: `swipe_profile`, `auto_pause_s`, `dwell_click`, `dwell_ms`, `click_sound`, `cursor_feedback`, `onboarding_done`.
## 7. tur — Enstrüman modu (2026-11-22)

Kullanıcı: kamerada iki el arasına sanal gitar telleri, parmakla vurunca gerçek zamanlı gitar sesi. Yönetici Claude (Opus 5.5).
Bu turda Codex ve Antigravity yok. Dal: `feature/instrument-mode`. Commit'i yalnız yönetici atar, push yok.
Başlangıç: tam takım 1455 geçti, 3 seçilmedi (manual).

| Sahip | Yazabileceği yollar |
|---|---|
| Claude yönetici | `contracts.py` (yalnız `Mode.INSTRUMENT`), `config.py` (şema 4), `tests/config/**`, `src/handcontrol/instrument/__init__.py`, `src/handcontrol/instrument/events.py`, `app.py`, `tests/app/**`, `tracking.py` (yalnız görüntü kancası), `README.md`, `CHANGELOG.md`, `Docs/reports/instrument.md`, bu dosya |
| Claude T (enstrüman motoru) | `src/handcontrol/instrument/geometry.py`, `strings.py`, `music.py`, `engine.py`, `session.py`, `tests/instrument/**` |
| Claude U (ses motoru) | `src/handcontrol/instrument/synth.py`, `src/handcontrol/instrument/audio.py`, `tests/audio/**` |
| Claude V (jest + denetleyici) | `gestures.py`, `controller.py`, `pipeline.py`, `tests/gestures/**`, `tests/controller/**`, `tests/integration/**` |
| Claude W (arayüz) | `src/handcontrol/ui/**`, `tests/ui/**` |
| Claude X (paketleme) | `requirements.txt`, `requirements.lock`, `pyproject.toml`, `THIRD_PARTY_NOTICES.md`, `packaging/**`, `scripts/build.ps1`, `tests/packaging/**` |

Sözleşmeler (yönetici yazdı, bu tur dondurulmuş):
- `contracts.Mode.INSTRUMENT = "instrument"`. Enstrüman modunda denetleyici yalnız `RELEASE_ALL` gönderebilir.
- `instrument/events.py`: `NoteOn`, `Bend`, `AllOff`, `StringView`, `HitView`, `InstrumentView`, ad listeleri
  (`SCALE_NAMES`, `CHORD_NAMES`, `LAYOUTS`, `TONES`, `LATENCIES`).
- Ayarlar şema 4: `instrument_layout`, `instrument_scale`, `instrument_quantize`, `instrument_chords`, `instrument_volume`,
  `instrument_tone`, `audio_device`, `audio_latency`, `instrument_particles`. `MODES` listesine `instrument` eklendi.
- `geometry/strings/music/engine/session` yalnız stdlib + `contracts` + `instrument.events` içe aktarır.
  `synth.py` numpy, `audio.py` sounddevice kullanır; saf modüller bunları içe aktarmaz.
- Mevcut testler değişmez. İstisnalar: şema sürümü sabiti (`== 3` → `== 4`, 2 satır) ve `Mode` üzerinde dolaşan
  parametreli testlerin yeni `INSTRUMENT` durumu (Enstrüman modunda pencere komutu yok).

### 7. tur kapanış (2026-11-22)

- Yönetici ayrıca yazdı: `src/handcontrol/instrument_runtime.py` (Qt bağlantısı), `tests/camera/test_tracking_image_tap.py`,
  `tests/ui/test_round6_ui.py` ve `tests/ui/test_ui_components.py` içinde yeni sekme/alan güncellemesi, sürüm 1.1.0.
- Bitiş: tam takım 1750 geçti, 7 manuel seçilmedi. Paket derlendi, `--self-test`: `OK ... audio=ok`.
- Donanım kabulü (gerçek kamera, ses kalitesi, gecikme hissi): bekliyor. Liste: `Docs/reports/instrument.md` §4.
