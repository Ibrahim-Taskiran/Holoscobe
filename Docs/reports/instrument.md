# Enstrüman modu: tasarım, ölçümler, elle test listesi

Tarih: 2026-11-22. Sürüm: 1.1.0. Dal: `feature/instrument-mode`.
Durum: otomatik testler geçti. **Gerçek kamera ve elle kabul: bekliyor.**

## 1. Tasarım

### Veri akışı

```
kamera -> TrackingLoop -> Pipeline.process -> FeatureExtractor -> GestureRecognizer -> Controller (eylem yok)
                                                  |
                                                  +-> frame observer: InstrumentSession.on_frame (tracking thread)
                                                        -> InstrumentEngine.update -> NoteOn/Bend -> AudioOutput kuyruğu (deque)
                                                        -> InstrumentView -> Qt sinyali -> InstrumentWindow (GUI thread)
Controller listener (her thread) -> InstrumentSession.on_snapshot -> etkin değilse anında AllOff(20 ms)
ses thread'i: PortAudio callback -> kuyruğu boşalt -> GuitarSynth.render -> çıkış
```

- Denetleyici yalnız modu tanır. Enstrüman modunda erken bir dal çalışır ve hiçbir eylem üretmez;
  ikinci katman olarak `_dispatch()` bu modda her eylemi reddeder. Sink'e yalnız `RELEASE_ALL` gidebilir.
- `InstrumentSession` etkinliği `mod = Enstrüman`, `durum = Etkin`, `kamera = Çalışıyor`, menü kapalı ve
  el çırpma adayı yok koşullarından çıkarır. Etkinlik düşünce bir kez `AllOff(20 ms)` gönderir. Duraklatma,
  acil durdurma, mod değişimi, kamera hatası, oturum kilidi ve otomatik duraklatma hep bu yoldan geçer.
- Ses akışı yalnız mod Enstrüman iken açıktır; moddan çıkınca ve uygulama kapanınca kapanır.
- Qt nesnelerine yalnız GUI thread dokunur. Kamera görüntüsü `TrackingLoop.on_image` kancasıyla yalnız
  pencere açıkken referans olarak tutulur; GUI zamanlayıcısı en yeni kareyi en çok bir kez `QImage`'a çevirir.

### Motor (saf, deterministik; yalnız stdlib + contracts)

| Konu | Değer |
|---|---|
| Tel | Tel elinin başparmak ucu (4) ile işaret ucu (8) arası doğru parçası |
| Solo perde | Tel uzunluğu 0,35–1,75 avuç birimi -> E5 (76) ... E3 (52), uzun tel = kalın ses |
| Dizi kilidi histerezisi | Derece sınırının 0,3 yarım ton ötesi |
| Perde bükme | ±2 yarım ton, One Euro (min_cutoff 4 Hz, beta 0,05), >0,02 değişimde gönderilir, en çok 2,5 s |
| Akor | 4 tel, 0,30 avuç aralık, avuç tarafının tersine; 0. tel en üstte, en kalın nota (Em = E2 B2 E3 G3) |
| Akor bölgesi | Avuç merkezi y, kare yüksekliğinin %15–85'i, 4 bölge, 0,03 histerezis |
| Çarpışma | Önceki ve şimdiki telin yan işareti (çapraz çarpım) + süpürülen parça kesişimi; tel uçlarının %4'ü sayılmaz |
| Histerezis bandı | ±0,06 avuç birimi (Schmitt); parmak karşı taraftan bandı terk edince vuruş |
| Yeniden tetikleme | Tel başına 60 ms |
| Hız -> şiddet | Alt eşik 2,0 avuç/s, tam şiddet 25 avuç/s, eğri 0,12 + 0,88·x^0,6; yukarı vuruş ×0,85 |
| Strum aralığı | Kesişme zamanı aradeğerlenir, `NoteOn.delay_ms` 5–25 ms adımlarla |
| Eller çok yakın | Parmak ucu tel avucuna 0,5 avuçtan, tel uçlarına 0,15 avuçtan yakın ya da iki avuç 0,9 avuçtan yakın |
| Yeni nota yok | DEGRADED/UNKNOWN, avuç ölçeği ≤ 0, `identity_ambiguous`, eksik/çift rol, kimlik değişimi, 150 ms'den uzun boşluk; dönüşteki ilk kare yalnız gözlem |

### Ses motoru (numpy, yeni ağır bağımlılık yok)

- Genişletilmiş Karplus-Strong: tek periyot gürültü uyarımı (şiddet hem düzey hem parlaklık), 0,13·P
  pena konumu tarağı, iki noktalı kayıp filtresi, kapalı biçimde çözülmüş doğrusal aradeğerli kesirli gecikme.
- Döngü FIR olduğu için özyineleme periyot uzunluğundaki parçalar halinde numpy ile hesaplanır; perde bükme
  parça başına güncellenir (8 ms yumuşatma).
- Sönüm: T60 = 6 s · 2^(−(midi−40)/24) (E2 ~6 s, E6 ~1,5 s), filtre kaybı temel frekansta dengelenir.
- 8 ses, en sessiz (eşitse en eski) ses 8 ms solmayla çalınır; aynı telde yeniden vuruş eski sesi 4 ms'de söndürür.
- Elektro: tanh sürüş + 3 dokunuşlu ton filtresi. Limiter: tavan −3 dBFS, ardından güvenlik kırpması.
- Çıkış: WASAPI paylaşımlı (auto_convert) -> DirectSound -> MME; 48 kHz (cihaz reddederse kendi hızı),
  Düşük 128 / Normal 256 örnek blok. Kuyruk 512 olay; taşarsa en eski olay düşer, `AllOff` her zaman uygulanır.
- 3 s callback gelmezse cihaz hatası sayılır.

### Jest çakışmaları (yalnız Enstrüman profilinde)

| Kural | Değer |
|---|---|
| El çırpma | Kurulmada ve aday girişinde iki elde de ≥ 4 başparmak dışı parmak açık |
| Mod menüsü | 5 parmak açık ve el sabit (≤ 0,12 avuç kayma; diğer modlarda 0,15) |
| Diğer modlar | Davranış değişmedi; profil her karede moddan uygulanır |

## 2. Ölçümler (bu makine, otomatik)

| Ölçüm | Sonuç | Hedef |
|---|---|---|
| Tracking thread ek süresi (300 kare, iki el akor strum, `InstrumentSession.on_frame`) | ort. 0,047 ms, p95 0,064 ms, en çok ~0,5 ms | < 2 ms/kare |
| Synth render, 8 ses, 128 örnek (2,67 ms) | medyan 0,094 ms (%3,5); elektro 0,100 ms | < %30 |
| Synth render, 8 ses, 256 örnek (5,33 ms) | medyan 0,138 ms (%2,6); elektro 0,148 ms; p95 ~0,21 ms | < %30 |
| FFT temel frekans hatası (E2, A2, E3, B3, E4, E5, E6) | ≤ 0,0001 % | ±%1 |
| Perde bükme +2 / −2 / +0,5 yarım ton | ≤ 0,0000 % | ±%1 |
| Çevrimdışı demo (8 akor strum = 32 nota, 6 strum elektro = 24 nota) | tepe 0,31, NaN/Inf yok | — |

Gerçek cihazda bir kez açılan akış (ses kalitesi dinlenmedi, ölçüm yalnız yazılım tarafı):

| Ayar | Cihaz | Çıkış gecikmesi | Callback ort. / en çok | Yük | Taşma | Vuruş -> ses (yazılım) |
|---|---|---|---|---|---|---|
| Düşük (128) | WASAPI, kulaklık, 48 kHz | 22 ms | 0,11 / 0,36 ms | 0,13 | 0 | 37 ms |
| Normal (256) | WASAPI, kulaklık, 48 kHz | 22 ms | 0,15 / 0,33 ms | 0,06 | 0 | 37 ms |

"Vuruş -> ses (yazılım)" = kare yakalama anından olayın callback'te işlenmesine kadar geçen süre + akışın
çıkış gecikmesi. Kamera pozlama süresi ve hoparlör dahil değildir. Not: Python 3.11'de Windows
`time.monotonic()` ~15,6 ms adımla ilerler; bu değer ~16 ms çözünürlüklüdür.

## 3. Otomatik testler

Başlangıç: 1455 geçti, 3 manuel. Bitiş: **1750 geçti, 7 manuel seçilmedi**.

| Klasör | Yeni test | Kapsam |
|---|---|---|
| `tests/instrument` | 130 | geometri, süpürülen kesişim (tek karede 4 tel), çift tetik yok, yön, hız eşiği, sıfır avuç, kalite/kimlik/boşluk, tüm dizi/akor adları, bölge ve dizi histerezisi, bükme sınırı ve yönü, oturum AllOff, performans |
| `tests/audio` | 71 (+4 manuel) | FFT perde, sönüm, NaN/Inf, limiter tavanı, bükme, ses çalma, AllOff solması, gecikmeli başlama, sahte akış: WASAPI/DirectSound/MME yedeği, cihaz hatası, istatistik |
| `tests/gestures` | 24 | zamanlı landmark fikstürleri: strum, çalarken yaklaşma, açık avuç clap, menü açma, el çaprazlanması, kimlik takası |
| `tests/controller` | 20 | Enstrüman modunda sink'e yalnız RELEASE_ALL; clap, menü, otomatik duraklatma, acil durdurma |
| `tests/integration` | 6 | Pipeline üzerinden dry-run oturum, profilin mod değişimini izlemesi, diğer modlar aynı |
| `tests/ui` | 17 | kıvılcım sınırı, pencere çizimi, ayna, ayarlar sekmesi, tepsi |
| `tests/app` | 15 | ses/pencere yaşam döngüsü, her durdurma yolunda tek AllOff, cihaz hatası, ayar uygulama, test sesi, görüntü kancası |
| `tests/config`, `tests/camera`, `tests/packaging` | 2 + 2 + 8 | şema 3 -> 4 kayıpsız taşıma, görüntü kancası, paket |

Değişen mevcut testler (zorunlu): şema sürümü sabiti (`== 3` -> `== 4`), 7 satırlı menüde satır konumu
(`test_ctrl_windows.py`, `test_integ_menus.py`), `Mode` üzerinde dolaşan yumruk testinden INSTRUMENT
durumunun çıkarılması, ayarlar penceresinde yeni sekme ve yeni alanlar (`test_round6_ui.py`, `test_ui_components.py`).

## 4. Elle test listesi (gerçek kamera; durum: bekliyor)

Komutsuz denemede (dry-run) yapılabilir. Kablolu kulaklık ya da hoparlör kullanın.

| # | Test | Ölçüt | Sonuç |
|---|---|---|---|
| 1 | Ayarlar → Enstrüman → Test sesi çal | Temiz, çıtırtısız arpej | bekliyor |
| 2 | Solo: 20 tek vuruş, farklı tel uzunlukları | 20 vuruşta 20 nota; kaçan ve çift nota sayısı | bekliyor |
| 3 | Akor: 20 strum (10 aşağı, 10 yukarı), 4 bölge | Her strumda 4 nota, doğru akor; kaçan tel sayısı | bekliyor |
| 4 | 5 dakika serbest çalma | Yanlış el çırpma (duraklatma) sayısı = 0, yanlış menü açılışı sayısı = 0 | bekliyor |
| 5 | Çalarken açık avuçla el çırpma | Kontrol duraklar, ses ~20 ms içinde kesilir | bekliyor |
| 6 | Sol el 5 parmak açık, sabit 600 ms | Mod menüsü açılır; başka moda geçince ses kesilir | bekliyor |
| 7 | Çalarken Ctrl+Alt+Shift+F12 | Ses anında kesilir | bekliyor |
| 8 | Çalarken Win+L | Ses anında kesilir | bekliyor |
| 9 | Çalarken USB kulaklığı çıkar | Türkçe bildirim, kontrol duraklar, mod İşaretçi | bekliyor |
| 10 | Solo: nota çalarken teli uzat/kısalt | Duyulur perde bükme, en çok ±2 yarım ton | bekliyor |
| 11 | Gecikme hissi (Düşük ve Normal) | Vuruş ile ses arası "anlık" mı; 1–5 puan | bekliyor |
| 12 | Enstrüman modunda imleç/klavye | İmleç kıpırdamaz, hiçbir tuş gitmez | bekliyor |
| 13 | Ayna açık/kapalı | Teller ve el iskeleti görüntüyle hizalı | bekliyor |

Önce ayarlanacak eşikler: vuruş alt hızı (2,0 avuç/s), histerezis bandı (0,06 avuç), el yakınlığı (0,5 avuç),
menü sabitliği (0,12 avuç).

## 5. Bilinen sınırlar

- Eşikler yalnız sentetik ellerle ayarlandı.
- Solo düzende tek tel tek sestir (gerçek tel gibi): yeni vuruş önceki notayı keser.
- Bluetooth ses aygıtları 100 ms'den fazla gecikme ekleyebilir.
- Dikey tutulan telde "aşağı/yukarı" strum yönü yana doğru hareket anlamına gelir.
- Not etiketi, 2,5 s'lik bükme süresi bittikten sonra son bükme değerini göstermeye devam edebilir (yalnız görsel).
