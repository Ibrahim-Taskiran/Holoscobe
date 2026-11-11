# Aşama 0 — Donanım başlangıç raporu

Tarih: 2026-11-12. Toplama yöntemi: PowerShell CIM sorguları, `scripts/monitor_probe.py` (ctypes, Per-Monitor-V2 DPI),
`scripts/camera_probe.py` (OpenCV, pencere açılmadı). Hepsi başsız (headless) çalıştı.

## Makine

| Alan | Değer |
|---|---|
| Model | HP Victus by HP Laptop 16-e0xxx (x64) |
| İşlemci | AMD Ryzen 5 5600H with Radeon Graphics — 6 çekirdek / 12 iş parçacığı, 3301 MHz taban |
| RAM | 23,3 GB görünür (24 GB kurulu sınıfı) |
| GPU (bilgi amaçlı; çıkarım CPU'da) | NVIDIA GeForce RTX 3060 Laptop GPU (sürücü 32.0.16.2101), AMD Radeon (TM) Graphics (sürücü 31.0.12044.3) |
| Windows | Windows 11 Pro, sürüm 10.0.26300, derleme 26300.9974, DisplayVersion 26H2, 64 bit |
| Güç | Pil var, ölçüm sırasında %100, AC'de (BatteryStatus=2). Güç planı CIM'den okunamadı. |
| Python | 3.11.18 x64 (uv tarafından yönetilen CPython) |
| Uzun yol desteği | `LongPathsEnabled = 0` (kapalı) |

## Kamera

| Alan | Değer |
|---|---|
| Cihaz | HP Wide Vision HD Camera (PnP sınıfı Camera, durum OK) — tek kamera, indeks 0 |

Ölçüm (`scripts/camera_probe.py`, her deneme ~3 s, 5 kare ısınma sonrası):

| Arka uç | İstenen | Gerçek | Ölçülen FPS | Açılış→ilk kare | Biçim | Okuma hatası |
|---|---|---|---|---|---|---|
| MSMF | 640x480@30 | 640x480 | **29,26** | 940 ms | 0x00000016 (MSMF dahili kod) | 0 |
| MSMF | 1280x720@30 | 1280x720 | **29,63** | 587 ms | 0x00000016 | 0 |
| DSHOW | 640x480@30 | 640x480 | 9,97 | 2156 ms | YUY2 | 0 |
| DSHOW | 1280x720@30 | 1280x720 | 10,30 | 2023 ms | MJPG | 0 |

Not: DSHOW sürücünün bildirdiği 30 fps'e rağmen ~10 fps veriyor. MSMF önce denenmeli. Işık koşulu kaydedilmedi
(oda ışığı, el yok); düşük ışıkta otomatik pozlama FPS'i düşürebilir — Aşama 1'de tekrar ölçülmeli.

## Ekran düzeni

Sanal masaüstü: sol-üst (0, 0), 3840x1080. Negatif koordinat **yok** (bu düzende).

| Aygıt | Birincil | Sınırlar (sol, üst, sağ, alt) | Çalışma alanı | Çözünürlük | Yenileme | DPI / ölçek |
|---|---|---|---|---|---|---|
| \\\\.\\DISPLAY6 | evet | 0, 0, 1920, 1080 | 0, 0, 1920, 1080 | 1920x1080 | 180 Hz | 96 / %100 |
| \\\\.\\DISPLAY1 | hayır | 1920, 0, 3840, 1080 | 1920, 0, 3840, 1080 | 1920x1080 | 144 Hz | 96 / %100 |

EDID adları (WmiMonitorID): "MSI G255F" (üretici MSI) ve adsız bir panel (üretici CMN = dizüstü paneli).
Eşleştirme tahmini: 180 Hz birincil = MSI G255F harici monitör, 144 Hz ikincil = dahili CMN panel. Bu eşleştirme
yenileme hızından çıkarıldı, doğrudan doğrulanmadı.

Çalışma alanı sınırlarla aynı: görev çubuğu otomatik gizleniyor olabilir (ölçüm anı). Negatif koordinat, farklı DPI ölçeği
ve dikey yerleşim testleri bu makinede şu an yok; Aşama'larda gereken senaryolar için monitör düzeni geçici olarak
değiştirilerek (ör. harici monitör sola alınarak) ölçülmeli → **bekliyor**.
