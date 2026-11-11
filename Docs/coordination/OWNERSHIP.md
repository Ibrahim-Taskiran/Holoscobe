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
| Claude D (denetleyici) | `src/handcontrol/controller.py`, `src/handcontrol/safety.py`, `src/handcontrol/dryrun.py`, `tests/controller/**` |
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
