# Holoscobe

Laptopun mevcut dahili kamerasıyla el hareketi kullanarak Windows 11 masaüstünü kontrol eden uygulama. Harici kamera gerektirmez. İki elin on parmağını ayrı takip eder, iki monitörü destekler, kurulumdan sonra internetsiz çalışır ve ücretli hiçbir araç ya da servis gerektirmez.

> **Durum: 1.1.0 ve sonrası (3B kedi maskot, Çizim modu, serbest teller, yeni arayüz). Donanım kabulü bekliyor.** Otomatik takım: **1978 otomatik test, 6 manuel test** (offscreen, sahte donanım). Dahili kamera ve gerçek ellerle kabul testleri tamamlanmadı: [ELLE_TEST.md](Docs/ELLE_TEST.md). Varsayılan dry-run Windows komutu göndermez; gerçek komutlar yalnız açık `--live` seçimi ve başarılı acil durdurma kısayolu kaydıyla kullanılabilir. Sürüm notları: [CHANGELOG.md](CHANGELOG.md).

## Ne yapar

Sekiz mod vardır: İşaretçi, Kaydırma, Yakınlaştırma, Ses, Pencereler, Komutlar, Enstrüman, Çizim.

| Mod | Hareket | Sonuç |
|---|---|---|
| Hepsi | İki elle bir kez el çırpma | Kontrolü açar ya da duraklatır |
| Hepsi (etkin, Enstrüman ve Çizim hariç) | Sağ yumruk tut (önce el açık olmalı) | Ön plandaki uygulama penceresini küçültür |
| Hepsi (etkin, Enstrüman ve Çizim hariç) | Sol yumruk tut (önce el açık olmalı) | Bu oturumda son küçültülen pencereyi geri açar |
| Hepsi | Otomatik duraklatma (Ayarlar'dan açılır) | Ayarlanan süre kullanılabilir el görünmezse kontrol duraklar |
| İşaretçi | İşaret açık, diğer parmaklar kapalı | İmleç hareket eder. Hızlı hareket uzağa, yavaş hareket hassas gider |
| İşaretçi | Eli aç (ya da kadrajdan çıkar) | İmleç hemen durur; el 200 ms açık kalırsa bırakılır. Eli geri getir, yeniden işaret et: kaldığı yerden devam eder |
| İşaretçi | Kısa başparmak + işaret pinch | Sol tık. İmleç pinch sırasında durur |
| İşaretçi | İki hızlı pinch (çeyrek ile yarım saniye arayla) | Çift tık |
| İşaretçi | Başparmak + işaret pinch'ini yerinde 0,8 sn tut | Anında sağ tık; bırakınca ikinci eylem oluşmaz |
| İşaretçi | Başparmak, işaret ve orta parmak uçlarını birleştir, taşı, bırak | Kavrayarak sürükle bırak; 120 ms sonra sol tuş basılır |
| İşaretçi | İşaret pinch kapalıyken sağ tıktan önce eli 0,6 avuçtan fazla taşı | Alternatif sürükle bırak |
| İşaretçi | Açık elden kısa başparmak + orta parmak pinch | Sağ tık |
| İşaretçi | İmleci yerinde sabit tut (Bekleyerek tıkla açıksa) | Sol tık; imlecin yanındaki halka dolunca tıklar |
| Kaydırma | Pinch + dikey hareket | Dikey kaydırma |
| Yakınlaştırma | İki elle pinch, elleri aç/kapat | Ctrl + tekerlek |
| Ses | Pinch + dikey hareket | Sistem sesi |
| Pencereler | Pinch'i 250 ms tut | Pencereyi sürükler |
| Pencereler | Kısa pinch | Küçült, büyüt, diğer monitöre taşı, kapat menüsü |
| Komutlar | Açık avuçla sola kaydır | Profile göre: Sonraki (Sunum), İleri (Tarayıcı), Sonraki parça (Medya), Sağdaki masaüstü (Masaüstleri) |
| Komutlar | Açık avuçla sağa kaydır | Profile göre: Önceki (Sunum), Geri (Tarayıcı), Önceki parça (Medya), Soldaki masaüstü (Masaüstleri) |
| Komutlar | Açık avuçla yukarı kaydır | Görev görünümü (tüm profillerde) |
| Komutlar | Açık avuçla aşağı kaydır | Masaüstünü göster (tüm profillerde) |
| Komutlar | Kısa pinch | Oynat / duraklat (Sunum profilinde Sonraki) |
| Enstrüman | Sağ işaret parmağıyla tele vur | Gitar sesi; Windows'a hiçbir komut gitmez (aşağıya bakın) |
| Çizim | Sağ işaret parmağıyla havada çiz | Kamera görüntüsünün üstünde 3B mürekkep; Windows'a hiçbir komut gitmez (aşağıya bakın) |

**Mod çarkı (her modda, kontrol etkinken):** Sol elle V yap (işaret + orta açık) ve yarım saniye tut; ekranın
ortasında çark açılır. V'yi bozmadan elini bir dilime götür, **yumruk yap: seçilir**. Avucu açmak ya da ortada
yumruk yapmak vazgeçer. El kaybolursa hiçbir şey seçilmez. Dilimler: İmleç, Kaydırma, Çizim, Enstrüman, Komutlar,
Diğer (Yakınlaştırma, Ses, Pencereler, Geri). Çark açıkken Windows'a komut gitmez, mürekkep ve ses üretilmez.

Kaydırma yönü kullanıcının bakışındandır: elini kendi soluna götürmek "sola kaydır"dır. Önizlemenin ayna ayarı bunu değiştirmez.

İmleç varsayılan olarak **göreli** çalışır (dokunmatik yüzey gibi). El ekranın tamamını
taramak zorunda değildir: işaret ederken el hareket ettikçe imleç o kadar kayar. Hızlı
hareket uzağa, yavaş hareket hassas gider; ikinci ekrana da böyle geçilir. Eli açmak ya da
kadrajdan çıkarmak debriyajdır: imleç yerinde kalır. Eli geri getirip yeniden işaret edince
kaldığı yerden devam eder. Gerçek fareyle imleci taşıdıysan oradan devam eder.
İmleç bir kez tutulunca yapışkandır: parmak durumu kısa süre belirsiz okunsa ya da takip
200 ms'den kısa bozulsa da bırakılmaz. Bırakmak için eli belirgin aç ya da yumruk yap.
Ekranın sağ üstündeki gösterge anlık durumu yazar (İmleç aktif / beklemede / Takip yok).
**Ayarlar** içinde **İmleç Türü** (Göreli / Mutlak) ve **İmleç Hızı** (0,5–2,0) seçilir.
Kalibrasyon dikdörtgeni yalnız **Mutlak** türde geçerlidir (kamera alanı = ekran).

Tıklamalar yalnız sağ elle ve İşaretçi modunda çalışır. Pinch sırasında imleç durur;
tık pinch başındaki konuma gider. İşaret pinch'ini 0,8 sn dolmadan bırakmak sol tık,
yerinde 0,8 sn tutmak anında ve yalnız bir kez sağ tıktır; iki hızlı pinch çift tıktır.
Başparmağı hem işaret hem orta parmak ucuna değdirip 120 ms tutmak kavrayarak sürüklemeyi
başlatır; eli taşı, kavramayı açınca sol tuş bırakılır. İkinci temas ilk temastan sonraki
60 ms karar penceresinde katılmalıdır. Yumruk kavrama değildir. Alternatif olarak işaret
pinch kapalıyken sağ tık oluşmadan eli 0,6 avuçtan fazla taşımak sürükleme başlatır.
Sürükleme başladıktan sonra sağ tık, sağ tık oluştuktan sonra sürükleme oluşmaz.
Açık elden başparmakla orta parmağı birleştirmek sağ tıktır (3 sn'ye kadar). Eski "işaret parmağını
kameraya doğru itme" tıklaması varsayılan olarak kapalıdır (kamera z tahmini güvenilir
değil). Sol el, baskın el ayarı ne olursa olsun imleci/tıklamayı yönetmez. Takip kaybında
basılı sol tuş en geç 200 ms içinde bırakılır. Tüm hareketler tepsideki **Hareket Rehberi**
menüsünde listelenir. Elle kontrol adımları: [ELLE_TEST.md](Docs/ELLE_TEST.md).

Yumruk komutundan önce elini en az 200 ms açık göster, sonra yumruğu yaklaşık 350 ms tut;
tekrar komut için yeniden aç.
Beş parmağın da bükülmüş algılanması gerekir. İki yumruk aynı anda komut üretmez. Sağ yumruk
tutulurken ön plandaki pencere değişirse işlem iptal edilir. Bu özellik tarayıcı içindeki
tek sekmeyi değil, uygulama penceresini küçültür/geri açar. Dry-run yalnız komut metnini
gösterir. Penceredeki **Sürdür / Duraklat** düğmesi kontrolü açar ve kapatır.

İmleç modu duraklatılmış başlar ve yalnız sen sürdürünce çalışır. Enstrüman ile Çizim seçilince kendiliğinden başlar
(Windows'a komut göndermezler); bunlardan düğme ya da tepsiyle bir masaüstü moduna dönünce kontrol yeniden duraklar.
Önceden sen sürdürdüysen etkin kalır. Ana pencere hiçbir modda kendiliğinden küçülmez.

## Enstrüman modu

Kamera önünde sanal gitar çalarsın. Varsayılan düzende telleri havada kendin çizersin; işaret parmağın tele
vurunca gerçek zamanlı gitar sesi çıkar. Bu modda Windows'a **hiçbir**
giriş komutu gitmez (imleç, tık, tuş, ses seviyesi, pencere yok); yalnız ses ve görüntü üretilir.
Bu yüzden komutsuz denemede (dry-run) de tam çalışır.

Açmak için sol şeritten, mod çarkından ya da tepsiden **Enstrüman**'ı seç. Ana pencerede kendi sahnesi açılır: kamera
görüntüsü, el iskeleti, parlayan teller, vuruşta kıvılcımlar, köşede çalan nota/akor. Üstteki çubukta düzen, son teli
sil, hepsini sil, hizala, tel sayısı, tını ve ses bulunur. Baskın el ayarı "sol" ise roller yer değiştirir.

Düzenler: **Serbest teller** (varsayılan), **Sabit teller**, **Solo**, **Akor**.

**Serbest tellerde notayı telin boyu belirler.** 0,15 kare yüksekliği en ince notayı (E5), 1,0 en kalın notayı (E3)
verir; arası seçili dizinin notalarına eşit bölünür (Mi minör pentatonikte 11 nota). Telin yeri ve yönü notayı
değiştirmez. Tel çizilirken, boyutlandırılırken ya da taşınırken **nota telin üstünde büyük yazar**; parmaklar açılmaya
başlayınca tel donar ve gördüğün notada kalır.

| Hareket | Sonuç |
|---|---|
| Solo ve Akor: sol elin başparmak ile işaret parmağını aç (tel) | Tel çizilir. Uzunluk avuç birimiyle ölçülür; kameraya uzaklık etkilemez |
| Sağ işaret parmağıyla teli geç | Nota çalar. Hızlı vuruş daha yüksek ve parlak ses verir; çok yavaş geçiş sayılmaz |
| Solo: teli uzat / kısalt | Perde değişir (uzun tel = kalın ses). Varsayılan dizi Mi minör pentatonik, 2 oktav |
| Solo: nota çalarken teli uzat / kısalt | ±2 yarım tona kadar perde bükme; elin titremesi doğal vibrato verir |
| Akor: sol eli yukarı/aşağı taşı | 4 bölgeden akor seçilir (varsayılan Em, C, G, D) |
| Akor: sağ elle 4 telin üstünden süpür | Strum: teller kesişme sırasıyla birkaç ms arayla çalar; aşağı ve yukarı ayrılır |
| İki elle çırp (iki elde de 4 parmak açık) | Kontrolü duraklatır / açar. Çalma pozu çırpma sayılmaz |
| Sol elle V, sabit tut (500 ms) | Mod çarkı. Tel tutma pozu çarkı açmaz |
| Sabit teller: herhangi bir elin işaret parmağıyla tellerin üstünden geç | Teller ekranda durur (3-8 tel, üstteki en kalın). İki el de çalar |
| Sabit teller: iki elle çimdikle, 0,4 sn tut, ellerini aç/kapat, bırak | Tel alanı iki çimdik noktası arasına taşınır ve boyutlanır; kaydedilir |
| Sabit teller: pencerede fareyle sürükle (köşeden boyutlandır) | Aynı ayar fareyle |
| Serbest teller: boş yerde çimdikle, 0,4 sn tut, çekerek bırak | Yeni tel çizilir (en çok 10). Uzun tel kalın, kısa tel ince ses verir |
| Serbest teller: telin ucunu / ortasını çimdikle, tut, sürükle | Uç: boyutlandır ve döndür. Orta: taşı. Çok kısaltıp bırakınca silinir |
| Serbest teller: iki elle bir telin iki ucunu tut (ya da boş yerde iki elle gerdir) | Tel iki çimdik arasında yeniden kurulur |
| Serbest teller: pencerede fareyle çiz / uçtan ya da ortadan sürükle, sağ tık sil, Delete hepsini sil | Aynı düzenleme fareyle |

İpuçları:
- Teli göğüs hizasında, kameraya yan değil düz tut. İki elin de tam görünmesi gerekir.
- Takip belirsizleşince (eller üst üste, kimlik karışması, kalite düşüşü) yeni nota çıkmaz; çalan notalar doğal söner.
- Duraklatma, acil durdurma (`Ctrl+Alt+Shift+F12`), mod değişimi, kamera hatası ve oturum kilidinde tüm ses ~20 ms içinde kesilir.
- Ses cihazı hatasında Türkçe bildirim çıkar; teller ekranda kalır, ses 3 saniyede bir yeniden denenir.

Ayarlar → **Enstrüman** sekmesi: düzen (Solo/Akor/Sabit teller/Serbest teller), sabit tel sayısı, serbest tel hizalama yardımı (yakın getirilen tel düzleşir, öbür telin yakın ucuyla ve aynı aralıkla hizalanır; boyu, dolayısıyla notası değişmez; kapalıysa tel bırakıldığı yerde kalır), dizi, diziye kilitle (kapalıysa Solo'da kesintisiz perde, serbest tellerde bütün yarım tonlar),
4 akor, ses düzeyi (varsayılan %50), tını (Temiz/Elektro), ses cihazı, gecikme (Düşük/Normal),
kıvılcım efektleri ve **Test sesi çal** düğmesi.

**Gecikme notu:** Ses WASAPI paylaşımlı modda 48 kHz, 128 (Düşük) ya da 256 (Normal) örneklik blokla
çalınır; açılamazsa DirectSound, sonra MME denenir. Toplam gecikme kamera (~33 ms kare) + izleme +
ses çıkışı (bu makinede WASAPI ~22 ms) toplamıdır. Bluetooth kulaklık 100 ms'den fazla ekleyebilir;
kablolu kulaklık ya da hoparlör önerilir. Tasarım ve ölçümler: [ENSTRUMAN.md](Docs/ENSTRUMAN.md).

## Çizim modu

Kamera görüntüsünün üstünde, ortadaki dikey eksenin çevresinde dönen 3B mürekkeple çizersin. Windows'a
hiçbir komut gitmez; komutsuz denemede de tam çalışır. **Çizim** düğmesi modu hemen başlatır.

| Hareket | Sonuç |
|---|---|
| Sağ el: yalnız işaret parmağı açık | Fırça. Parmak ucunda mürekkep bırakır |
| Sağ el: dört parmak açık | Taşı. İz bırakmadan başka yere geç |
| Sağ el: yumruk | Silgi. İlk değdiği yüzeyi siler (önde mürekkep varsa ön). Arkadakini silmek için yumruğu açıp o izin üstünde yeniden kapat |
| Sağ el: başparmakla işareti birleştir (en az iki parmak açık), tut | Renk çarkı açılır. Elini bir renge götür, parmaklarını ayır: seçilir. Ortada ayırmak vazgeçer. 8 renk |
| Sol el: dört parmak açık, sağa ya da sola yatır | Sahneyi o yöne döndürür; çok yatırmak hızlandırır, dik tutmak durdurur. Aynı anda çizersen sarmal oluşur |
| Ön kolları göğüs önünde X yapıp tut (ya da pencerede **Temizle**) | Sol üstteki yüzde dolunca bütün mürekkep aşağı akıp silinir. Kollar birbirini kapatsa da sayılır; kalemle öbür kolun üstüne uzanmak silmez |
| El çırpma, `Ctrl+Alt+Shift+F12` | Duraklatır. Mürekkep ekranda kalır |

X hareketi `pose_landmarker_lite.task` modelini ister (`scripts\setup.ps1` indirir). Model yoksa çizim çalışır,
yalnız X ile temizleme kapalı kalır ve ekranda bildirilir. Çizim bellekte tutulur, dosyaya kaydedilmez; çok uzun
çizimlerde (yaklaşık 18 kamera genişliği iz) en eski mürekkep silinir. Tasarım ve ölçümler: [CIZIM.md](Docs/CIZIM.md).

## 3B Kedi Maskot

Kamera açıkken bütün modlarda ekranın sağ alt köşesinde şeffaf, tıklama geçiren ve odak
çalmayan 3B tüylü bir kedi penceresi gösterilir. Gri, sarı gözlü ve tek dişli kedi proje sahibinin kendi modelidir.

- **Gerçek zamanlı taklit:** Baş dönüşü, bakış yönü, göz kırpma, çene, gülümseme ve kaş hareketlerini (`face_landmarker.task`),
  kolları (`pose_landmarker_lite.task`) ve patileri (mevcut el takibi) ayna görüntüsü gibi kopyalar. Kollarını X yapınca
  kedi de yapar; pati yüze ve gövdeye gömülmez, önünden geçer.
- **El takibine öncelik:** Yüz ve poz algılama ayrı bir arka plan iş parçacığında düşük hızda çalışır; kedi gizliyken
  tamamen durur.
- **Masaüstü dostu:** İmleç kedinin üstüne gelince yarı saydamlaşır, tıklamaları altındaki pencereye geçirir. Kimse
  algılanmadığında göz kırpar ve fare imlecini takip eder.
- **Açma / kapatma:** Ana pencere başlığındaki **Kedi** düğmesinden, tepsiden ya da **Ayarlar > Genel** altından
  anında açılıp kapatılabilir.
- **Enstrüman modunda** kedinin arkasından küçük notalar yükselir; tele her vuruş yeni nota çıkarır (`mascot/notes.py`).
- **Çizim modunda** kalem çizerken (ya da renk çarkı açıkken) sağ eli taklit eden patiye seçili renkte bir fırça gelir.
- **Ana pencere** kendiliğinden küçülmez; küçültmek tamamen kullanıcıya aittir.
- **Gereksinim:** Offscreen OpenGL 3.3 gerekir. Desteklenmeyen sistemlerde kedi devre dışı kalır, masaüstü kontrolü
  normal çalışmaya devam eder.

Veri akışı, çarpışma kuralları ve modeli Blender ile yeniden üretme: [KEDI_MASKOT.md](Docs/KEDI_MASKOT.md).

## İlk açılış eğitimi

Uygulama ilk açılışta bir eğitim penceresi gösterir. Büyük hedeflerle pratik yaptırır. Adımlar:

1. Holoscobe'a hoş geldin (duruş ipuçları)
2. İmleci hedeflere götür
3. Hedefe tıkla
4. Çift tıkla
5. Sağ tık
6. Kutuyu sürükle bırak
7. Kaydırma ve Komutlar
8. Hazırsın!

Her adımı **Atla** ile geçebilirsin. Eğitim bir kez açılır; bitince ya da atlanınca `onboarding_done` kaydedilir. Eski ayar dosyasıyla gelen kullanıcıya eğitim gösterilmez.

## Komutlar modu ve uygulama profilleri

Komutlar modunda açık avuçla kaydırarak klavye ve medya tuşları gönderilir. Kaydırma: açık avuç (en az 3 parmak açık), hızlı ve belirgin hareket. Bir kaydırmadan sonra kısa süre başka kaydırma çalışmaz ve ters yön kilitlenir; böylece geri dönüş hareketi komut üretmez.

Profil, **Ayarlar > Hareketler** içindeki `swipe_profile` ayarıyla seçilir. Varsayılan `auto`: ön plandaki uygulamanın exe adına bakar. Tanınmayan uygulama Masaüstleri profilini kullanır.

| Profil | Exe adları | Sola / sağa kaydır |
|---|---|---|
| Sunum | `powerpnt.exe`, `soffice.bin`, `acrord32.exe`, `acrobat.exe`, `sumatrapdf.exe`, `foxitpdfreader.exe`, `microsoft.photos.exe`, `photos.exe` | Sonraki / Önceki |
| Tarayıcı | `chrome.exe`, `msedge.exe`, `firefox.exe`, `opera.exe`, `brave.exe`, `vivaldi.exe`, `explorer.exe` | İleri / Geri |
| Medya | `spotify.exe`, `vlc.exe`, `wmplayer.exe`, `music.ui.exe`, `applemusic.exe`, `mpc-hc64.exe` | Sonraki parça / Önceki parça |
| Masaüstleri (varsayılan) | diğer her uygulama | Sağdaki masaüstü / Soldaki masaüstü |

Yukarı kaydırma (Görev görünümü) ve aşağı kaydırma (Masaüstünü göster) her profilde aynıdır. Kısa pinch Sunum profilinde Sonraki, diğerlerinde Oynat / duraklat gönderir.

## Geri bildirim

- **İmleç halkası:** Basılı tutma sırasında imlecin yanında ilerleme halkası dolar. Ayarlardan kapatılabilir (`cursor_feedback`).
- **Komut bildirimi:** Gönderilen komut imlecin yanında kısa süre yazar (ör. "Sonraki parça").
- **İptal bildirimi:** Tık, sağ tık ya da sürükleme iptal olunca nedeni yazar.
- **Tık sesi:** Tık ve komutta kısa sistem sesi. Varsayılan kapalı (`click_sound`).

## Ayarlar

Ana penceredeki sol şeritten ya da tepsiden açılır. Sol kenar çubuğunda beş kategori vardır:

| Kategori | İçerik |
|---|---|
| Genel | Kamera, ayna görüntüsü, baskın el, varsayılan mod, otomatik duraklat, acil durdurma kısayolu, monitör eşlemesi, katman/bildirim/kedi maskot, Windows ile başlat |
| İmleç | Hassasiyet ön ayarı, imleç türü, hız, hassasiyet, yumuşatma, bekleyerek tıkla ve süresi, tık sesi, imleç halkası |
| Hareketler | Pinch eşikleri, kaydırma ve yakınlaştırma yönü, kaydırma profili (Komutlar) |
| Enstrüman | Düzen (Serbest/Sabit/Solo/Akor), dizi, diziye kilitle, sabit tel sayısı, serbest tel hizalama yardımı, 4 akor bölgesi, ses düzeyi, tını (Temiz/Elektro), ses cihazı, gecikme, kıvılcım efektleri, Test sesi çal |
| Gelişmiş | Kamera altyapısı, algılama/takip eşikleri, dry-run paneli, ayarları içe/dışa aktar, ilk açılış eğitimi, tanılama raporu |

**Hassasiyet ön ayarları:** Hassas (hız 0,7), Normal (hız 1,0), Hızlı (hız 1,5). Değerleri elle değiştirirsen ön ayar **Özel** olur.

**İçe/dışa aktarma:** "Ayarları dışa aktar…" ve "Ayarları içe aktar…" düğmeleri ayarları dosyaya yazar ve dosyadan okur. İçe aktarılan değerler doğrulanır; geçersiz alanlar sınırlanır ya da yok sayılır.

**Bekleyerek tıkla:** Varsayılan kapalı. Açıksa imleç `dwell_ms` (varsayılan 1000 ms) boyunca yerinde durunca sol tık gider.

## Güvenlik

- Uygulama duraklatılmış başlar.
- Acil durdurma kısayolu: `Ctrl+Alt+Shift+F12`.
- 150 ms'den eski kamera örneği komuta dönüşmez.
- Takip kaybolursa uygulamanın bastığı tüm girişler en geç 200 ms içinde bırakılır.
- Pencere kapatma yalnız normal kapatma isteğiyle yapılır; süreç sonlandırılmaz, kaydedilmemiş belge uyarısı korunur.
- Normal çalışmada görüntü kaydedilmez. Kareler yalnız bilgisayarda işlenir.

## Gereksinimler

- Windows 11 x64
- Laptopun mevcut dahili kamerası (geliştirme sırasında laptopun dahili kamerası kullanıldı; harici kamera gerekmez)
- Kaynaktan çalıştırmak için: Python 3.11 ve [uv](https://docs.astral.sh/uv/)
- Hazır paketi kullanmak için Python gerekmez.

## Kurulum (hazır paket)

Yönetici yetkisi gerekmez.

1. Sürüm zip'ini (`Holoscobe-<sürüm>-win64.zip`) ve `.sha256` dosyasını indir. Hash'i karşılaştır: `Get-FileHash .\Holoscobe-<sürüm>-win64.zip -Algorithm SHA256`.
2. Zip'i bir klasöre aç.
3. Açılan klasörde çalıştır:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1            # Başlat Menüsü kısayolu
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Desktop   # Masaüstü kısayolu da
```

Betik uygulamayı `%LOCALAPPDATA%\Programs\Holoscobe` içine kopyalar. `-DryRun` yalnız yapılacakları yazar.

Kaldırmak için:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Çalışan süreci durdurur, Windows ile başlat kaydını, kısayolları ve program klasörünü siler. Ayarlar ve günlükler `%LOCALAPPDATA%\Holoscobe` altında kalır.

**SmartScreen:** Exe imzasız. İlk açılışta "Windows bilgisayarınızı korudu" uyarısı çıkabilir. **Ek bilgi > Yine de çalıştır** seçilir. İmzalama henüz yok.

Paket yaklaşık 390 MB açık, 156 MB zip. Sürümü kendin üretmek için: `scripts\release.ps1` (`dist\Holoscobe-<sürüm>-win64.zip` ve `.sha256` üretir). Ayrıntı: [PAKETLEME.md](Docs/PAKETLEME.md).

## Kurulum (kaynaktan)

```powershell
.\scripts\setup.ps1
```

Betik sanal ortamı kurar, sabitlenmiş paketleri yükler, el (`hand_landmarker.task`), poz (`pose_landmarker_lite.task`) ve yüz (`face_landmarker.task`) modellerini indirir ve SHA-256 değerlerini `assets/model_manifest.json` ile karşılaştırır. Model dosyaları depoya dahil değildir. Çevrimdışı kurulum için `-ModelPath`, `-PoseModelPath` ve `-FaceModelPath` parametreleri kullanılabilir.

## Çalıştırma

Proje kökünde, hazırlanmış `.venv` ile:

```powershell
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe -m handcontrol.app          # dry-run, üretilecek komutları gösterir
.venv\Scripts\python.exe -m handcontrol.app --live   # gerçek Windows komutları
```

Seçenekler: `--live` (gerçek komutlar), `--telemetry` (oturum telemetrisini yerel CSV'ye yazar, görüntü kaydetmez; ayrıntı: [TELEMETRI.md](Docs/TELEMETRI.md)), `--log-level DEBUG|INFO|WARNING|ERROR` (günlük düzeyi, varsayılan `INFO`).

Alternatif: `powershell -ExecutionPolicy Bypass -File scripts\launch.ps1` (dry-run); aynı komuta `--live` eklenebilir. Normal kullanımda `QT_QPA_PLATFORM=offscreen` ayarlı olmamalıdır.

Uygulama Paused başlar. Kamera sağlıklı olduktan sonra tepsiden Sürdür ile veya el çırparak etkinleştirin. Ardından sağ işaret parmağıyla imleci taşıyın, kısa pinch ile tıklayın; diğer hareketler için tepsideki Hareket Rehberi'ne bakın. Tepsiden kamerayı kapatabilir, ayarları/kalibrasyonu açabilir ve çıkabilirsiniz. Kısayol çakışırsa canlı başlatma reddedilir; dry-run ayarlarından başka bir kısayol seçin. Kamera hatası ve kurtarma otomatik etkinleştirme yapmaz. Gerçek donanım kabulü tamamlanana kadar önce dry-run kullanın.

Masaüstündeki tek `Holoscobe` kısayolunu güncel kaynak koduna bağlamak için
`powershell -ExecutionPolicy Bypass -File scripts\update_shortcuts.ps1` çalıştırın. Betik simgeyi
`%LOCALAPPDATA%\Holoscobe\icons` altına içeriğine göre adlandırarak kopyalar; böylece Windows simge önbelleği eski
simgeyi göstermez.
Kısayol `scripts\holoscobe.pyw` dosyasını konsolsuz ve gerçek fare kontrolüyle (`--live`) açar; kod değişince yeniden derleme gerekmez.

Uygulama koyu grafit ve kayısı temalı tek bir ana penceredir (`ui/main_window.py`): solda mod şeridi (`İmleç`, `Kaydırma`, `Enstrüman`, `Çizim`, `Diğer` ve `Ayarlar`), üstte durum/Kedi/Ayrıntı/Sürdür başlık çubuğu, ortada kamera sahnesi, altta (ya da geniş ekranda yanda) seçili moda göre değişen hareket ipuçları yer alır. Enstrüman ve Çizim seçilince aynı pencerede kendi sahne ve araç çubuklarıyla açılır.

## Sorun giderme

**Tanılama paketi:** **Ayarlar > Gelişmiş > Tanılama raporu oluştur** düğmesi (ya da tepsi menüsü) paketi üretir. `Holoscobe-tanilama-<tarih>.zip` Masaüstüne yazılır (Masaüstü yoksa kullanıcı klasörüne). İçinde günlükler, kamera, ekran ve ayar bilgisi bulunur; görüntü yoktur. Hata bildirirken bu zip'i ekle.

**Günlük dosyası:** `%LOCALAPPDATA%\Holoscobe\logs\holoscobe.log`. Döner günlüktür (1 MB, 3 yedek: `holoscobe.log.1` ...). Ayrıntı için `--log-level DEBUG`.

**Tek örnek koruması:** Aynı anda yalnız bir Holoscobe çalışır. İkinci kez açarsan "Holoscobe zaten çalışıyor" yazar ve kapanır. Pencere görünmüyorsa tepsiye bak. Gerekirse Görev Yöneticisi'nden süreci bitir.

**El algılanmıyor ya da imleç titriyor:**
- Dirseğini masaya koy. Kol havada yorulur ve el titrer.
- Kameraya 40–70 cm uzakta dur.
- Yüzün önden aydınlık olsun. Arkandan pencere ışığı gelmesin.
- Elin kadrajda tam görünsün; parmaklar birbirinin arkasında kalmasın.
- Kamerayı başka uygulama kullanıyorsa kapat.

**Kısayol kaydı reddedildi:** `Ctrl+Alt+Shift+F12` başka bir şeye ayrılmış olabilir. Ayarlar > Genel'den başka bir kombinasyon seç ve `--live`'ı yeniden başlat.

## Testler

```powershell
.\scripts\run_tests.ps1
```

Tüm otomatik testler için (kamera/masaüstü açılmaz):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
```

Fareyi oynatan, sesi değiştiren ya da pencere açan testler `manual` olarak işaretlidir ve varsayılan olarak atlanır. CI (`.github/workflows/ci.yml`) her push ve PR'da testleri çalıştırır.

### Gerçek kamera kabul testleri

Bunları bir insan, gerçek elleriyle çalıştırır. Sonuçlar `Docs/reports/hw_*` altına yazılır ve depoya girmez.
Tam liste: [ELLE_TEST.md](Docs/ELLE_TEST.md).

```powershell
.venv\Scripts\python.exe -m handcontrol.tools.finger_test      # on parmak, 400 sunum
.venv\Scripts\python.exe -m handcontrol.tools.stability_test   # 5 dakika iki el
.venv\Scripts\python.exe -m handcontrol.tools.clap_test        # el çırpma
.venv\Scripts\python.exe -m handcontrol.tools.profile_compare  # 480p ve 720p karşılaştırma
```

## Performans

- **Tek el hızlı yolu** (`adaptive_hands.py`): tek el görünürken kare başına 29 ms yerine 14 ms (sentetik kare, Ryzen 5 5600H). İkinci el ayrı iş parçacığında aranır; Yakınlaştırma ve Enstrüman'da kapalıdır.
- **Boşta bekleme:** kontrol duraklatılmışken ve 2 saniyedir el yokken izleme 30 yerine 10 FPS çalışır; el görünen ilk karede tam hıza döner.
- **Kedi:** yüz ve gövde takibi ayrı iş parçacığında, düşük hızda; kedi gizliyken tamamen durur.

## Yapı

```
src/handcontrol/
  app.py               Masaüstü giriş noktası ve bileşen bağlama
  contracts.py         Modüller arası ortak tipler
  camera.py            Kamera yaşam döngüsü, en yeni kare tamponu
  tracking.py          MediaPipe Hand Landmarker sarmalayıcısı
  adaptive_hands.py    Tek el görünürken tek el modeli
  background.py        Ortak iş parçacığı tabanı ve saat
  features.py          Parmak durumu, avuç ölçeği, el kimliği
  filters.py           One Euro filtresi, durum kilidi, yüzdelik
  gestures.py          Pinch, el çırpma, yumruk tanıyıcıları
  mode_wheel.py        Sol V mod çarkı ve çizim renk çarkı geometrisi
  relative_pointer.py  Göreli imleç (debriyaj ve ivme)
  middle_pinch.py      Başparmak + orta parmak sağ tık tanıyıcısı
  index_tap.py         Eski ileri itme tıklaması (varsayılan kapalı)
  swipe.py             Açık avuç kaydırma tanıyıcısı, Komutlar profilleri
  dwell.py             Bekleyerek tıkla
  controller.py        Durum makinesi, modlar, eylem üretimi
  pipeline.py          Uçtan uca kare işleme boru hattı
  mapping.py           Kamera alanını iki monitöre eşleme
  safety.py            Eski örnek reddi, bağımsız zaman aşımı gözcüsü
  dryrun.py            Windows'a dokunmayan sahte alıcı
  config.py            Sürümlü ayar dosyası (şema 4)
  diagnostics.py       Tanılama paketi (zip)
  telemetry.py         İsteğe bağlı yerel oturum telemetrisi (CSV)
  logsetup.py          Döner günlük dosyası, yakalanmamış hata kancaları
  drawing.py           3B dönen mürekkep sahnesi ve derinlikli silme
  drawing_gestures.py  Çizim modu el/poz hareketleri (X temizleme, renk çarkı)
  drawing_raster.py    NumPy tabanlı hızlı mürekkep çizici
  instrument/          Sanal gitar motoru (geometri, serbest teller, müzik, Karplus-Strong sentez, WASAPI ses)
  instrument_runtime.py Enstrüman oturumu, ses ve pencere yaşam döngüsü
  mascot/              3B tüylü kedi maskot (OpenGL 3.3, yüz/poz takibi, retarget, kemikler, notalar, şeffaf pencere)
  windows/             Win32 bağdaştırıcıları (giriş, pencere, ses, kısayol, oturum, tuş komutları, başlangıç)
  ui/                  PySide6 ana pencere, koyu tema, kart ayarlar, tepsi, önizleme, kalibrasyon, eğitim, katmanlar, Enstrüman/Çizim görünümleri
                       (ui/painted.py: boyanan pencerelerin ortak gövdesi, ui/widgets.py: ortak bileşenler)
  tools/               Konsol kabul testi ve ölçüm araçları (common.py: ortak ToolRun)
assets/                İkon, model manifesti, 3B kedi varlıkları (cat.npz)
tests/                 Her modülün kendi test klasörü
scripts/               Kurulum, test, başlatma, kısayol, maskot üretimi, derleme, install/uninstall, release betikleri
packaging/             PyInstaller spec ve giriş noktası
.github/workflows/     CI (ci.yml) ve sürüm (release.yml)
Docs/                  Şartname, mod belgeleri, paketleme, elle test listeleri
```

Akış: kamera → en yeni kare → takip → özellikler → jestler → denetleyici → eylem → Windows bağdaştırıcısı.

## Benzer araçlardan öğrenilenler

Camera Mouse, eViacam, Project Gameface ve Ultraleap TouchFree incelendi. Bu inceleme şu özelliklerin eklenmesine yön verdi: ilk açılış eğitimi, tutma hareketleri için imleç halkası, kaydırmayla komutlar, bekleyerek tıkla ve hassasiyet ön ayarları. Bu araçlarla başarım karşılaştırması yapılmadı.

## Belgeler

- [Sürüm notları](CHANGELOG.md)
- [Enstrüman modu: tasarım ve ölçümler](Docs/ENSTRUMAN.md)
- [Çizim modu: tasarım ve ölçümler](Docs/CIZIM.md)
- [3B kedi maskot](Docs/KEDI_MASKOT.md)
- [Elle test listesi](Docs/ELLE_TEST.md) ve [Windows senaryoları](Docs/WINDOWS_TESTLERI.md)
- [Paketleme ve sürüm](Docs/PAKETLEME.md)
- [Oturum telemetrisi](Docs/TELEMETRI.md)
- [Teknik şartname (v1.1, ilk plan)](Docs/Windows_Hand_Gesture_Control_Spec.md)
- [Üçüncü taraf lisans bildirimleri](THIRD_PARTY_NOTICES.md)

## Bilinen sınırlar

- Tek RGB kamera, başka bir elin arkasında kalan parmağı göremez. Model tahmini ölçüm sayılmaz; kalite düşünce komutlar askıya alınır.
- Yönetici yetkisiyle çalışan uygulamalar ve korumalı Windows ekranları kapsam dışıdır.
- Yakınlaştırma, hedef uygulamanın Ctrl + tekerlek desteğine bağlıdır.
- Komutlar modundaki kısayollar (masaüstü değiştirme, medya tuşları) hedef uygulamanın ve Windows'un o kısayolu desteklemesine bağlıdır.
- Enstrüman modunun eşikleri (vuruş hızı, histerezis bandı, el yakınlığı, menü sabitliği) yalnız sentetik verilerle ayarlandı; gerçek kamerada ayar bekliyor.
- Çizim modunun eşikleri (X kanıtı, silgi derinliği, dönme hızı) sentetik verilerle ayarlandı; gerçek kamerada deneme bekliyor.
- Ayarlar'daki Yumuşatma oranı, Algılama ve Takip güven eşikleri, Kısa durum bildirimleri ve Dry-run paneli seçenekleri henüz hiçbir şeyi etkilemez ve kaydedilmez.
- 3B kedi maskot için OpenGL 3.3 gerekir; desteklenmeyen sistemlerde kedi gizlenir, masaüstü kontrolü etkilenmez.
- Gerçek kamera ve ellerle kabul testi bekliyor.

## Lisans

Projenin kendi kaynak lisansı henüz belirlenmedi; lisans eklenene kadar bütün hakları saklıdır. Kullanılan üçüncü taraf bileşenlerin lisansları `THIRD_PARTY_NOTICES.md` dosyasındadır.
