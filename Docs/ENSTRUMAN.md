# Enstrüman modu: tasarım ve ölçümler

Güncelleme: 2026-11-26. Durum: otomatik testler geçti; gerçek kamera kabulü bekliyor ([ELLE_TEST.md](ELLE_TEST.md)).
Hareket tablosu: [README](../README.md#enstrüman-modu).

## 1. Tasarım

### Veri akışı

```
kamera -> TrackingLoop -> Pipeline.process -> FeatureExtractor -> GestureRecognizer -> Controller (eylem yok)
                                                  |
                                                  +-> frame observer: InstrumentSession.on_frame (tracking thread)
                                                        -> InstrumentEngine.update -> NoteOn/Bend -> AudioOutput kuyruğu (deque)
                                                        -> InstrumentView -> Qt sinyali -> InstrumentWindow (ana pencerenin sayfası, GUI thread)
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

### Düzenler

| Düzen | Tel | Nota |
|---|---|---|
| Serbest (varsayılan) | Kullanıcı çizer, en çok 10 | Telin boyu: 0,15–1,0 kare yüksekliği, seçili dizinin E5–E3 notalarına eşit bölünür |
| Sabit | Ekranda 3–8 yatay tel | Üstteki en kalın; alan çimdikle ya da fareyle taşınır |
| Solo | Sol elin başparmak-işaret arası | Tel uzunluğu (avuç birimi), perde bükme |
| Akor | Sol elin yanında 4 paralel tel | Sol elin yüksekliği akoru seçer |

Serbest teller (`instrument/freeform.py`, `engine.free_pitch`):

- Çimdik 400 ms tutulunca başlar (0,35 avuç altı), 0,55 üstünde biter. 0,45'i geçince tel artık hareket etmez; böylece
  bırakırken nota değişmez.
- Düzenlenen telin notası `StringView.label` ile gelir ve telin üstünde büyük yazılır. Fareyle düzenlemede aynı hesap
  `free_note` ile yapılır.
- Hizalama yardımı: 7° içinde yatay/dikeye düzleştirir, paralel telin yakın ucuna ve var olan aralığa oturtur. Telin
  boyunu değiştirmez.
- "Diziye kilitle" kapalıysa bütün yarım tonlar kullanılır. 0,06 kare yüksekliğinden kısa bırakılan tel silinir.
- Çimdikleyen el vurmaz; tel düzenlenirken hiçbir tel çalmaz. 250 ms'ye kadar takip kaybı düzenlemeyi bölmez.

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
| Mod çarkı | Sol elle V, sabit tutma (≤ 0,12 avuç kayma; diğer modlarda 0,15). Çimdiklerken açılmaz |
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

## 3. Bilinen sınırlar

- Eşikler yalnız sentetik ellerle ayarlandı.
- Solo düzende tek tel tek sestir (gerçek tel gibi): yeni vuruş önceki notayı keser.
- Bluetooth ses aygıtları 100 ms'den fazla gecikme ekleyebilir.
- Dikey tutulan telde "aşağı/yukarı" strum yönü yana doğru hareket anlamına gelir.
- Not etiketi, 2,5 s'lik bükme süresi bittikten sonra son bükme değerini göstermeye devam edebilir (yalnız görsel).
