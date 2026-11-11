# Aşama 0 — Ücretsiz teknik temel: test raporu

Tarih: 2026-11-12. Hazırlayan: Claude A (temel). Kanıt dosyaları bu raporda adıyla anılır.

## Ortam

- HP Victus 16-e0xxx, AMD Ryzen 5 5600H (6C/12T), 23,3 GB RAM, Windows 11 Pro 10.0.26300.9974 (26H2) x64.
- Kamera: HP Wide Vision HD Camera (tek, indeks 0). Ekranlar: 2 x 1920x1080, %100 ölçek, yan yana (0,0)–(3840,1080).
- Ayrıntı: `Docs/reports/phase0_hardware.md`.

## Yazılım

- Python 3.11.18 x64, `.venv`, kurulum aracı `uv`.
- Sabit sürümler (`requirements.lock`, 35 paket, SHA-256 karmalı; `pyproject.toml` `dependencies`):
  mediapipe 1.2.2, opencv-contrib-python 5.0.0.93, PySide6-Essentials 6.12.0 (+ shiboken6 6.12.0), pycaw 20260927,
  comtypes 1.5.0, pyinstaller 6.22.3, pytest 9.2.0.
- Tekerlek etiketleri: mediapipe `py3-none-win_amd64`, numpy `cp311-cp311-win_amd64`, opencv `cp37-abi3-win_amd64`,
  PySide6/shiboken6 `cp310-abi3-win_amd64` → 3.11 x64 ile uyumlu. Python sürümü değiştirilmedi.
- Model: `hand_landmarker.task` float16/1 (GCS generation 1682480004222387), SHA-256
  `fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`. Manifest: `assets/model_manifest.json`.

## Koşul

- Tüm komutlar başsız; pencere açılmadı, fare/klavye/ses değiştirilmedi (pycaw yalnız okuma yaptı).
- Çıkarım: CPU delegesi, VIDEO modu, num_hands=2, 640x480 sentetik kareler (el yok).
- Kamera: oda ışığı, kadrajda el yok, ölçüm başına ~3 s. Işık düzeyi ölçülmedi.
- Yol testi: proje kopyası `...\scratchpad\Holo Test Çalışma ğü` (boşluk + Türkçe karakter) içinde sıfırdan venv.

## Deney

| # | Deney | Komut / kanıt |
|---|---|---|
| D1 | Paket kurulumu ve içe aktarma | `uv pip install ...`; `import mediapipe, cv2, PySide6.QtWidgets, pycaw, comtypes, PyInstaller, pytest` |
| D2 | Kilit dosyası | `uv pip compile ... --generate-hashes` → `requirements.lock`; `uv pip freeze` ile birebir aynı (35 paket) |
| D3 | Model indirme + lisans | resmi URL, sunucu MD5 = indirilen MD5; model kartı PDF s.2 "Apache License, Version 2.0" |
| D4 | CPU çıkarım | `scripts/smoke_inference.py --frames 100` |
| D5 | Kamera | `scripts/camera_probe.py` (MSMF → DSHOW, 640x480 ve 1280x720) |
| D6 | Ses bağlayıcısı | pycaw ile varsayılan uç noktanın sesini okuma (değiştirmeden) |
| D7 | Kurulum betikleri | Türkçe+boşluklu yolda `setup.ps1` (sıfırdan), tekrar çalıştırma, `-ModelPath` (çevrimdışı), bozuk karma, `run_tests.ps1`, `launch.ps1` |
| D8 | Model yükleme yolu | Türkçe yolda `model_asset_path` ve `model_asset_buffer`; yalnız boşluklu ASCII yolda `model_asset_path` |

## Sonuç

- D1: tümü temiz içe aktarıldı. `mediapipe`, `opencv-contrib-python` istiyor; `opencv-python` ile birlikte kurulunca ikisi aynı
  `cv2/` klasörüne yazıyor. Bu yüzden yalnız contrib tutuldu. MSMF ve DSHOW arka uçları mevcut.
- D3: Bağımsız yayımlanmış SHA-256 bulunamadı. MediaPipe deposundaki `external_files.bzl` farklı bir test dosyasını
  (`32d1eab9…`) sabitliyor. Kayıt: "computed at retrieval, independent review pending". Sunucu MD5'i aynı kaynaktan
  geldiği için yalnız aktarım bütünlüğü sayılır, bağımsız inceleme sayılmaz.
- D4: model yükleme 59–62 ms. Isınmış kare süresi ortalama 11,5–12,3 ms, medyan 11,2–11,3 ms, p95 13,3–15,3 ms,
  ilk kare 14–15 ms. Sentetik karede el yok, yani ağırlıkla avuç algılayıcı çalıştı. Gerçek elde landmark modeli de çalışır,
  süre artar → gerçek el ölçümü **bekliyor**.
- D5: MSMF 640x480 → 29,26 fps, 1280x720 → 29,63 fps; DSHOW ~10 fps (iki çözünürlükte). İstenen çözünürlükler aynen alındı.
  Okuma hatası 0. Kamera her denemeden sonra bırakıldı.
- D6: varsayılan uç nokta okundu (ses 0,315, sessiz değil). Yazma denenmedi (kural 7).
- D7: `setup.ps1` sıfırdan çıkış 0; tekrar çalıştırmada model "zaten doğrulandı", çıkış 0; `-ModelPath` çevrimdışı kopya
  çıkış 0; manifestteki karma bozulunca çıkış 1, "MODEL SHA-256 MISMATCH" ve dosya silindi; `run_tests.ps1` 1 passed;
  `launch.ps1` Python'u ve `src` yolunu doğru buldu, `handcontrol.app` henüz yok → "No module named handcontrol.app".
- D8: **Bulgu.** MediaPipe 1.2.2, `model_asset_path` içinde ASCII dışı karakter olunca `FileNotFoundError: Unable to open file`
  veriyor. Boşluklu ASCII yolda sorun yok. `model_asset_buffer=<bytes>` Türkçe yolda çalıştı (medyan 10,3 ms).
  `src/handcontrol/tracking.py:55` şu an `model_asset_path` kullanıyor → `Docs/coordination/REQUESTS_A.md` içinde bildirildi.
- Ek: `LongPathsEnabled=0`. PySide6 dosyaları site-packages altında 151 karaktere iniyor. Derin proje kökünde (>~85 karakter)
  Explorer/PowerShell silme işlemleri 260 sınırına takıldı (uv kurulumu etkilenmedi). `setup.ps1` uyarı veriyor.

## Karar

Aşama 0 geçiş kapısı maddeleri:

| Madde | Durum | Kanıt |
|---|---|---|
| Proje yapısı (A'nın alanı: `scripts/`, `assets/`, kilit, bildirimler) mevcut dosyalar korunarak | geçti | `pyproject.toml` pytest bloğu değişmedi; yeni dosyalar yalnız A alanında |
| Donanım kaydı: kamera modeli, işlemci, RAM, Windows, ekran düzeni | geçti | `phase0_hardware.md` |
| Ekran düzeni: negatif koordinat / karışık DPI senaryosu | bekliyor | bu düzende yok; düzen değiştirilerek ölçülmeli |
| Python 3.11 x64'te MediaPipe Tasks, OpenCV, PySide6 Community, pycaw/comtypes uyumu | geçti | D1, D6 |
| Paketleyici (PyInstaller) uyumu | bekliyor | içe aktarma geçti; tek klasör derleme denemesi paketleme aşamasında |
| Çalışan sürümlerin sabitlenmesi | geçti | `requirements.lock` (karmalı), `pyproject.toml` |
| Yerel CPU çıkarım, GPU zorunluluğu yok | geçti | D4 (sentetik kare) |
| Gerçek elle çıkarım süresi | bekliyor | gerçek el / kamera akışıyla ölçülmeli |
| Kamera çözünürlük ve gerçek FPS | geçti | D5 |
| Bağımlılık lisans envanteri | geçti | `THIRD_PARTY_NOTICES.md` |
| Model lisansı (kütüphaneden ayrı kanıt) | geçti | Model kartı s.2 Apache-2.0, resmi belge tablosundan bağlantılı (D3). Not: kart 2021 tarihli, bağ resmi belge tablosu üzerinden |
| Model SHA-256 önceden incelenmiş karşı doğrulama | bekliyor | bağımsız karma yok; ikinci makine/ağdan insan incelemesi gerekli |
| Modelin pakete eklenmesi | bekliyor | lisans izin veriyor; karma incelenene kadar setup indiriyor |
| Ücretli SDK / deneme / API anahtarı / bulut yok | geçti | `THIRD_PARTY_NOTICES.md` "Zero-cost check" |
| PySide6 modülleri için LGPL yükümlülük planı | geçti | `THIRD_PARTY_NOTICES.md` "LGPL items" (modül bazlı son kontrol UI listesi kesinleşince) |
| Kurulum betiği: venv + kilitli paketler + model + karma doğrulama, hata olunca durma | geçti | D7 |
| Boşluklu ve Türkçe karakterli yoldan çalışma | kaldı (çözümü hazır) | D8: `model_asset_path` Türkçe yolda çöküyor; `tracking.py` buffer'a geçince yeniden test |
| Temiz Windows kullanıcı hesabında başlatma | bekliyor | uygulama modülü henüz yok |
| `launch.ps1` ile uygulama açılışı | bekliyor | `handcontrol.app` henüz yok |

**Genel karar:** Ücretsiz bileşenlerle yerel CPU çıkarımı bu makinede çalışıyor; model lisansı (Apache-2.0) kanıtlandı.
Geliştirme için Aşama 1'e geçilebilir. Dağıtım tarafı (modeli pakete koyma, sürüm) bağımsız karma incelemesi ve
Türkçe yol düzeltmesi bitene kadar **bekliyor**. Doğrulanmayan hiçbir madde "geçti" yazılmadı.
