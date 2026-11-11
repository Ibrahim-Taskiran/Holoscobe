# Claude A (temel) — durum ve istekler

## 2026-11-12 — Paketler kuruldu (.venv, Python 3.11.18 x64)
mediapipe 1.2.2, opencv-contrib-python 5.0.0.93, PySide6-Essentials 6.12.0 (+ shiboken6 6.12.0),
pycaw 20260927, comtypes 1.5.0, pyinstaller 6.22.3, pytest 9.2.0. Kilit: `requirements.lock`.

- Not (herkes): `opencv-python` KURULU DEĞİL. mediapipe `opencv-contrib-python` ister; ikisi aynı `cv2/` klasörünü
  paylaştığı için yalnız contrib tutuldu. `import cv2` normal çalışır (MSMF ve DSHOW arka uçları var).
- Not (Antigravity/UI): yalnız PySide6-Essentials var (QtCore/QtGui/QtWidgets/QtNetwork/QtSvg vb.). QtQuick3D, QtWebEngine,
  QtCharts gibi Addons modülleri yok. Gerekirse buraya yazın; lisans etkisini (bazı Addons modülleri GPL/ticari) birlikte bakarız.
- Model yolu: `assets/models/hand_landmarker.task` (manifest: `assets/model_manifest.json`).

## ÖNEMLİ bulgu — Claude E (tracking.py) için
MediaPipe 1.2.2, `BaseOptions(model_asset_path=...)` yolunda ASCII dışı karakter varsa (ör. `C:\Users\Çağrı\...`,
`Holo Test Çalışma`) modeli açamıyor: `FileNotFoundError: Unable to open file at ...`. Boşluklu ASCII yol sorunsuz.
Ölçüldü 2026-11-12 (`scripts/smoke_inference.py --use-path` ile tekrar edilebilir).
Çözüm: `BaseOptions(model_asset_buffer=Path(model_path).read_bytes(), delegate=CPU)`. Ölçülen yük ~60 ms, fark yok.
`src/handcontrol/tracking.py:55` şu an `model_asset_path` kullanıyor. Şartname "boşluklu yoldan başlatma" istiyor;
Türkçe kullanıcı adları gerçek risk.

## Diğer notlar
- Windows'ta uzun yol desteği kapalı (LongPathsEnabled=0). PySide6 dosyaları site-packages altında 151 karaktere kadar iniyor.
  Proje kökü ~85 karakteri geçerse bazı dosyalar 260'ı aşar. setup.ps1 uyarı veriyor.
- Kamera: MSMF ~29,5 fps (640x480 ve 1280x720), DSHOW yalnız ~10 fps → kamera kodu MSMF'yi önce denemeli.
  MSMF açılış ~0,6–0,9 s, DSHOW ~2 s. Ayrıntı: `Docs/reports/phase0_report.md`.

## Yöneticiye istekler
- (yok)
