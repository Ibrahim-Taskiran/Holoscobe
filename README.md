# Holoscobe

Kamerayla el hareketi kullanarak Windows 11 masaüstünü kontrol eden uygulama. İki elin on parmağını ayrı takip eder, iki monitörü destekler, kurulumdan sonra internetsiz çalışır ve ücretli hiçbir araç ya da servis gerektirmez.

> **Durum: uygulama bağlandı; donanım kabulü bekliyor.** Kamera → pipeline → denetleyici → arayüz zinciri ve güvenlik yaşam döngüsü hazır. Son otomatik takım: **1039 geçti, 3 manuel test seçilmedi** (offscreen, sahte donanım). Gerçek kamera, el ve iki monitör doğrulaması henüz yapılmadı. Varsayılan dry-run Windows komutu göndermez; gerçek komutlar yalnız açık `--live` seçimi ve başarılı acil durdurma kısayolu kaydıyla kullanılabilir.

## Ne yapar

| Mod | Hareket | Sonuç |
|---|---|---|
| Hepsi | İki elle bir kez el çırpma | Kontrolü açar ya da duraklatır |
| Hepsi (etkin) | Sağ yumruk tut (önce el açık olmalı) | Ön plandaki uygulama penceresini küçültür |
| Hepsi (etkin) | Sol yumruk tut (önce el açık olmalı) | Bu oturumda son küçültülen pencereyi geri açar |
| İşaretçi | İşaret açık, diğer parmaklar kapalı | İmleç hareket eder. Hızlı hareket uzağa, yavaş hareket hassas gider |
| İşaretçi | Eli aç (ya da kadrajdan çıkar) | İmleç hemen durur; el 200 ms açık kalırsa bırakılır. Eli geri getir, yeniden işaret et: kaldığı yerden devam eder |
| İşaretçi | Kısa başparmak + işaret pinch | Sol tık. İmleç pinch sırasında durur |
| İşaretçi | İki hızlı pinch (çeyrek ile yarım saniye arayla) | Çift tık |
| İşaretçi | Başparmak + işaret pinch'ini yerinde 0,8 sn tut | Anında sağ tık; bırakınca ikinci eylem oluşmaz |
| İşaretçi | Başparmak, işaret ve orta parmak uçlarını birleştir, taşı, bırak | Kavrayarak sürükle bırak; 120 ms sonra sol tuş basılır |
| İşaretçi | İşaret pinch kapalıyken sağ tıktan önce eli 0,6 avuçtan fazla taşı | Alternatif sürükle bırak |
| İşaretçi | Açık elden kısa başparmak + orta parmak pinch | Sağ tık |
| Kaydırma | Pinch + dikey hareket | Dikey kaydırma |
| Yakınlaştırma | İki elle pinch, elleri aç/kapat | Ctrl + tekerlek |
| Ses | Pinch + dikey hareket | Sistem sesi |
| Pencereler | Pinch'i 250 ms tut | Pencereyi sürükler |
| Pencereler | Kısa pinch | Küçült, büyüt, diğer monitöre taşı, kapat menüsü |

Mod değiştirmek için baskın olmayan elin açık avucunu 600 ms sabit tut.

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
menüsünde listelenir. Ayrıntı ve elle kontrol adımları: [click_controls.md](Docs/reports/click_controls.md).
Bu hareketlerin gerçek kamera kabulü henüz yapılmadı.

Yumruk komutundan önce elini en az 200 ms açık göster, sonra yumruğu yaklaşık 350 ms tut;
tekrar komut için yeniden aç.
Beş parmağın da bükük algılanması gerekir. İki yumruk aynı anda komut üretmez. Sağ yumruk
tutulurken ön plandaki pencere değişirse işlem iptal edilir. Bu özellik tarayıcı içindeki
tek sekmeyi değil, uygulama penceresini küçültür/geri açar. Dry-run yalnız komut metnini
gösterir. Önizleme üstündeki **Sürdür / Duraklat** düğmesinden kontrolü etkinleştirebilirsin.

## Güvenlik

- Uygulama duraklatılmış başlar.
- Acil durdurma kısayolu: `Ctrl+Alt+Shift+F12`.
- 150 ms'den eski kamera örneği komuta dönüşmez.
- Takip kaybolursa uygulamanın bastığı tüm girişler en geç 200 ms içinde bırakılır.
- Pencere kapatma yalnız normal kapatma isteğiyle yapılır; süreç sonlandırılmaz, kaydedilmemiş belge uyarısı korunur.
- Normal çalışmada görüntü kaydedilmez. Kareler yalnız bilgisayarda işlenir.

## Gereksinimler

- Windows 11 x64
- Web kamerası (HP Victus dahili kamerasıyla geliştiriliyor)
- Python 3.11
- [uv](https://docs.astral.sh/uv/) (kurulum betiği kullanır)

## Kurulum

```powershell
.\scripts\setup.ps1
```

Betik sanal ortamı kurar, sabitlenmiş paketleri yükler, el modelini indirir ve SHA-256 değerini `assets/model_manifest.json` ile karşılaştırır. Model dosyası depoya dahil değildir.

## Çalıştırma

Proje kökünde, hazırlanmış `.venv` ile:

```powershell
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe -m handcontrol.app          # dry-run, üretilecek komutları gösterir
.venv\Scripts\python.exe -m handcontrol.app --live   # gerçek Windows komutları
```

Alternatif: `powershell -ExecutionPolicy Bypass -File scripts\launch.ps1` (dry-run); aynı komuta `--live` eklenebilir. Normal kullanımda `QT_QPA_PLATFORM=offscreen` ayarlı olmamalıdır.

Uygulama Paused başlar. Kamera sağlıklı olduktan sonra tepsiden Sürdür ile veya el çırparak etkinleştirin. Ardından sağ işaret parmağıyla imleci taşıyın, kısa pinch ile tıklayın; diğer hareketler için tepsideki Hareket Rehberi'ne bakın. Tepsiden kamerayı kapatabilir, ayarları/kalibrasyonu açabilir ve çıkabilirsiniz. Kısayol çakışırsa canlı başlatma reddedilir; dry-run ayarlarından başka bir kısayol seçin. Kamera hatası ve kurtarma otomatik etkinleştirme yapmaz. Gerçek donanım kabulü tamamlanana kadar önce dry-run kullanın.

Masaüstündeki `Holoscobe` ve `Holoscobe - Canli` kısayollarını güncel kaynak koduna bağlamak için
`powershell -ExecutionPolicy Bypass -File scripts\update_shortcuts.ps1` çalıştırın.
Bu kısayollar gerçek fare kontrolü ve telemetriyle (`--live --telemetry`) başlatır.

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

Fareyi oynatan, sesi değiştiren ya da pencere açan testler `manual` olarak işaretlidir ve varsayılan olarak atlanır.

### Gerçek kamera kabul testleri

Bunları bir insan, gerçek elleriyle çalıştırır. Sonuçlar `Docs/reports/hw_*` altına yazılır.

```powershell
.venv\Scripts\python.exe -m handcontrol.tools.finger_test      # on parmak, 400 sunum
.venv\Scripts\python.exe -m handcontrol.tools.stability_test   # 5 dakika iki el
.venv\Scripts\python.exe -m handcontrol.tools.clap_test        # el çırpma
.venv\Scripts\python.exe -m handcontrol.tools.profile_compare  # 480p ve 720p karşılaştırma
```

## Yapı

```
src/handcontrol/
  contracts.py     Modüller arası ortak tipler
  camera.py        Kamera yaşam döngüsü, en yeni kare tamponu
  tracking.py      MediaPipe Hand Landmarker sarmalayıcısı
  features.py      Parmak durumu, avuç ölçeği, el kimliği
  filters.py       One Euro filtresi, histerezis
  gestures.py      Pinch, el çırpma, menü bekleme tanıyıcıları
  controller.py    Durum makinesi, modlar, eylem üretimi
  mapping.py       Kamera alanını iki monitöre eşleme
  safety.py        Eski örnek reddi, bağımsız zaman aşımı gözcüsü
  dryrun.py        Windows'a dokunmayan sahte alıcı
  config.py        Sürümlü ayar dosyası
  windows/         Win32 bağdaştırıcıları (giriş, pencere, ses, kısayol, oturum)
  ui/              PySide6 tepsi, önizleme, kalibrasyon, ayarlar, katmanlar
  tools/           Konsol kabul testi araçları
tests/             Her modülün kendi klasörü
scripts/           Kurulum, test ve başlatma betikleri
Docs/              Şartname, yol haritası, raporlar
```

Akış: kamera → en yeni kare → takip → özellikler → jestler → denetleyici → eylem → Windows bağdaştırıcısı.

## Belgeler

- [Teknik şartname](Docs/Windows_Hand_Gesture_Control_Spec.md)
- [Yol haritası](Docs/ROADMAP_TR.md)
- [Doküman incelemesi ve kararlar](Docs/DOKUMAN_INCELEME_TR.md)
- [Aşama 0 raporu](Docs/reports/phase0_report.md)
- [Üçüncü taraf lisans bildirimleri](THIRD_PARTY_NOTICES.md)

## Bilinen sınırlar

- Tek RGB kamera, başka bir elin arkasında kalan parmağı göremez. Model tahmini ölçüm sayılmaz; kalite düşünce komutlar askıya alınır.
- Yönetici yetkisiyle çalışan uygulamalar ve korumalı Windows ekranları kapsam dışıdır.
- Yakınlaştırma, hedef uygulamanın Ctrl + tekerlek desteğine bağlıdır.

## Lisans

Projenin kendi kaynak lisansı henüz belirlenmedi. Bu depo özeldir; kamuya dağıtımdan önce lisans netleştirilecektir. Kullanılan üçüncü taraf bileşenlerin lisansları `THIRD_PARTY_NOTICES.md` dosyasındadır.
