# Sürüm ve paketleme

## Derleme
`scripts\build.ps1` — model SHA-256 doğrulanır, PyInstaller (6.22.3) ile pencereli onedir derleme: `dist\Holoscobe\Holoscobe.exe`.
Spec (`packaging\holoscobe.spec`) `assets\` klasörünü (el modeli, manifest, `icon.ico`) paketler ve model hash'i uyuşmazsa derlemeyi durdurur.
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
- Manifest: model SHA-256'sı henüz bağımsız gözden geçirilmedi; sürümde paketlemek için `sha256_status` kapatılmalı (`assets\model_manifest.json`).
- Paket yaklaşık 390 MB açık, 156 MB zip. İmzasız exe: SmartScreen uyarısı verebilir.
