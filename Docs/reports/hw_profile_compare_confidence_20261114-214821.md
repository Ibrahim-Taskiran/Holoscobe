# İzleyici güven profili karşılaştırması

Dosya: `hw_profile_compare_confidence_20261114-214821` - Durum: **tamam**

| Alan | Kaydedilen bilgi |
|---|---|
| Ortam | CPU: AMD Ryzen 5 5600H with Radeon Graphics (12 çekirdek)<br>Windows: Windows 10 (10.0.26300)<br>kamera: profiller={'0.55/0.55/0.55': {'arka_uc': 'msmf', 'istenen': '640x480@30', 'gercek_cozunurluk': '640x480', 'kamera_fps': 30.2, 'el_etiketi_degisimi': False}, '0.5/0.35/0.35': {'arka_uc': 'msmf', 'istenen': '640x480@30', 'gercek_cozunurluk': '640x480', 'kamera_fps': 30.2, 'el_etiketi_degisimi': False}, '0.5/0.25/0.25': {'arka_uc': 'msmf', 'istenen': '640x480@30', 'gercek_cozunurluk': '640x480', 'kamera_fps': 30.0, 'el_etiketi_degisimi': False}} |
| Yazılım | Paketler: mediapipe 1.2.2, opencv-contrib-python 5.0.0.93, numpy 2.4.6, python 3.11.18<br>Model SHA-256 (manifest): fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1<br>Model SHA-256 (dosya): fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1 (eşleşiyor) |
| Koşul | Işık: tavan lambası<br>Arka plan: dağınık oda<br>Mesafe: 50-70cm |
| Deney | Sabit poz listesi (5 poz) x 8 sn, her güven profilinde aynı sırayla.<br>Profil: algılama/varlık/izleme eşiği. Çözünürlük: 640x480 |
| Sonuç | 0.55/0.55/0.55: kullanılabilir 0.867, eli olmayan 0.082, en uzun boşluk 1781.0 ms, 22.0 FPS<br>0.5/0.35/0.35: kullanılabilir 0.839, eli olmayan 0.024, en uzun boşluk 1031.0 ms, 21.8 FPS<br>0.5/0.25/0.25: kullanılabilir 0.922, eli olmayan 0.003, en uzun boşluk 157.0 ms, 13.6 FPS |
| Karar | **geçti**<br>Ölçüm tamamlandı (bilgi amaçlı; kabul kapısı yok). |

## Güven profili karşılaştırması

| Profil (alg/varlık/izleme) | Kullanılabilir kare oranı | Eli olmayan kare oranı | En uzun boşluk ms | İşlenen FPS | Örnek |
|---|---|---|---|---|---|
| 0.55/0.55/0.55 | 0.867 | 0.082 | 1781.0 | 22.0 | 993 |
| 0.5/0.35/0.35 | 0.839 | 0.024 | 1031.0 | 21.8 | 926 |
| 0.5/0.25/0.25 | 0.922 | 0.003 | 157.0 | 13.6 | 914 |

Not: Görüntü karesi ve ham landmark izi kaydedilmedi. Ayar yapılan denemeler ile kabul denemeleri farklı diziler olmalıdır.
