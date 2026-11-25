# Çizim modu

Kamera görüntüsünün üstünde, ortadaki dikey eksenin çevresinde dönen 3B mürekkep. Windows'a hiçbir komut gitmez.
Hareket tablosu: [README](../README.md#çizim-modu).

Durum (2026-11-26): kod ve otomatik testler tamam. Eşikler gerçek kamerada ayar bekliyor.

## Parçalar

| Dosya | Görev |
|---|---|
| `drawing.py` | Mürekkep sahnesi: ortak eksenin yerel uzayında lekeler, ön/arka yüzey silgisi, temizleme akışı, 8 renk |
| `drawing_gestures.py` | El rolleri, araç onayı, renk çarkı, X algılama |
| `drawing_raster.py` | Dönen ve akan sahne için NumPy çizici |
| `ui/drawing_view.py` | Kamera üstünde çizim, durum yazısı, kedinin fırçasına renk bildirimi |

## Kararlar

- Mürekkep 4000 lekeyle sınırlı; aşılınca en eskisi silinir.
- Araç 100 ms onay ister, 160 ms'ye kadar kopma izi bölmez. Ham parmak kıvrımına göre hemen durur.
- Silgi önce ilk değdiği yüzeyi siler; arkadakini silmek için yumruk yeniden kapatılır.
- Renk çarkı: sağ elle birleştirip 180 ms tut, dilime götür, ayır. En az iki öbür parmak açık olmalı; yumruk açmaz.
- Mod çarkı (sol V) bu modda da açılır; sol açık avuç yalnız döndürür.
- Duraklatma ve mod değişimi mürekkebi silmez, yalnız izi keser. Uygulama kapanınca çizim kaybolur.

## X ile silme

Ön kollar göğüs önünde X yapılıp tutulur. Kanıt üç yoldan gelir; biri yeter:

1. Poz modelinde kesişen ön kollar.
2. Poz modelinde yer değiştirmiş eller (bilek ve parmak kökü ortalaması). Dirsekler kadrajda olmasa da çalışır.
3. El modelinde yer değiştirmiş, dışa yatık iki el. Poz modeli bilekleri açıkça ayrı görüyorsa sayılmaz.

| Kural | Değer |
|---|---|
| Gereken kanıt | 480 ms |
| Kaçan karede kanıt kaybı | geçen sürenin %25'i |
| Görünürlük eşiği | omuz 0,45; bilek ve dirsek 0,30 |
| Kalem pozu | X sayılmaz (çizen el öbür kolun üstüne uzanabilir) |
| Alkış adayı | kanıtı sıfırlamaz |

Sentetik kol modeliyle 5 saniyelik 150'şer deneme:

| Durum | Eski kural | Şimdiki kural |
|---|---|---|
| X, kollar birbirini kapatıyor | 29 sildi | 150 sildi, ortanca 0,7 sn |
| X, görüş iyi | 130 | 150, ortanca 0,5 sn |
| Kalemle kolun üstüne uzanma | 6 | 0 |
| Kolları kavuşturma | 1 | 0 |

X, `pose_landmarker_lite.task` modelini ister. Model yoksa çizim çalışır, X kapalı kalır; pencerede **Temizle** düğmesi vardır.

## Ölçümler (2026-11-24, bu makine)

| Ölçüm | Sonuç |
|---|---|
| El + poz izleme (640×480, medyan) | 23,6 ms/kare; yalnız el 11,9 ms |
| Boyama, durağan sahne (5700 leke) | 1,7 ms |
| Boyama, dönen sahne (3470 leke) | 11 ms |
| Boyama, temizleme akışı (3470 leke) | 9–10 ms |

Testler: `scripts\run_tests.ps1 tests\drawing`.
