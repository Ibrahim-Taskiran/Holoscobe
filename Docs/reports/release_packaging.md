# Sürüm ve paketleme

## Derleme
`scripts\build.ps1` — manifestteki tüm modellerin (`hand_landmarker.task`, `pose_landmarker_lite.task`, `face_landmarker.task`) SHA-256 değeri doğrulanır, PyInstaller (6.22.3) ile pencereli onedir derleme üretilir: `dist\Holoscobe\Holoscobe.exe`.
Spec (`packaging\holoscobe.spec`) `assets\` klasörünü (modeller, manifest, `icon.ico`, `mascot/` kedi varlıkları), `PySide6.QtOpenGL` modülünü (3B kedi maskot) ve Enstrüman modu için yalnız `_sounddevice_data/portaudio-binaries/libportaudio64bit.dll` dosyasını paketler; herhangi bir model hash'i uyuşmazsa derlemeyi durdurur.
CI için `HOLOSCOBE_PYTHON` ortam değişkeni .venv yerine başka Python'u seçer.

## Kendini sınama (pencere ve kamera yok)
`Holoscobe.exe --self-test <rapor.txt>` — modülleri içe aktarır, Qt eklentilerini ve model hash'ini denetler, MediaPipe ile boş görüntüde modeli çalıştırır.
Exe pencereli olduğu için sonuç dosyaya yazılır. Başarıda ilk satır `OK self-test ...`, çıkış kodu 0.

## Sürüm paketi
`scripts\release.ps1 [-SkipBuild]` — derler, self-test çalıştırır, `dist\Holoscobe-<sürüm>-win64.zip` ve `.sha256` üretir.
Sürüm `pyproject.toml` içindeki `version` alanından okunur.

## Kurulum / kaldırma (yönetici gerekmez)
- `scripts\install.ps1 [-Source <klasör>] [-Desktop] [-DryRun]` — `%LOCALAPPDATA%\Programs\Holoscobe` içine kopyalar, Başlat Menüsü (ve isteğe bağlı Masaüstü) kısayolu oluşturur.
- `scripts\uninstall.ps1 [-DryRun]` — işlemi durdurur, HKCU Run değeri `Holoscobe` (`startup.py` ile aynı), kısayolları ve program klasörünü siler.
- `-DryRun` yalnız yapılacakları yazar.

## CI
- `.github\workflows\ci.yml` — main'e push ve PR: windows-latest, Python 3.11, `pip install --require-hashes -r requirements.lock`, `QT_QPA_PLATFORM=offscreen`, `python -m pytest -q`. Testler gerçek model dosyasını gerektirmez.
- `.github\workflows\release.yml` — `v*` etiketi: modeli manifest URL'sinden indirip SHA-256 doğrular, `release.ps1` çalıştırır, zip + sha256'yı `gh release create` ile (yerleşik `GITHUB_TOKEN`) yükler.

## Notlar
- Manifest: `hand_landmarker.task` 2026-11-18'de yeniden doğrulandı ve sürümde paketlenmesine onay verildi; `pose_landmarker_lite.task` ve `face_landmarker.task` sürüm indirmelerinden hesaplanan SHA-256 ile denetlenir (`assets\model_manifest.json`).
- İmzasız exe: SmartScreen uyarısı verebilir.
