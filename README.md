# Holoscobe

Laptopun mevcut dahili kamerasıyla el hareketi kullanarak Windows 11 masaüstünü kontrol eden uygulama. Harici kamera gerektirmez. İki elin on parmağını ayrı takip eder, iki monitörü destekler, kurulumdan sonra internetsiz çalışır ve ücretli hiçbir araç ya da servis gerektirmez.

> **Durum: 1.0.0. Otomatik testler geçti, donanım kabulü bekliyor.** Son otomatik takım: **1455 geçti, 3 manuel test seçilmedi** (offscreen, sahte donanım). Dahili kamera ve gerçek ellerle kabul testleri bir insan tarafından henüz yapılmadı. Varsayılan dry-run Windows komutu göndermez; gerçek komutlar yalnız açık `--live` seçimi ve başarılı acil durdurma kısayolu kaydıyla kullanılabilir. 1.0 durumu: [manager_status.md](Docs/reports/manager_status.md). Sürüm notları: [CHANGELOG.md](CHANGELOG.md).

## Ne yapar

Altı mod vardır: İşaretçi, Kaydırma, Yakınlaştırma, Ses, Pencereler, Komutlar.

| Mod | Hareket | Sonuç |
|---|---|---|
| Hepsi | İki elle bir kez el çırpma | Kontrolü açar ya da duraklatır |
| Hepsi (etkin) | Sağ yumruk tut (önce el açık olmalı) | Ön plandaki uygulama penceresini küçültür |
| Hepsi (etkin) | Sol yumruk tut (önce el açık olmalı) | Bu oturumda son küçültülen pencereyi geri açar |
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

Mod değiştirmek için baskın olmayan elin açık avucunu 600 ms sabit tut.

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
menüsünde listelenir. Ayrıntı ve elle kontrol adımları: [click_controls.md](Docs/reports/click_controls.md).
Bu hareketlerin gerçek kamera kabulü henüz yapılmadı.

Yumruk komutundan önce elini en az 200 ms açık göster, sonra yumruğu yaklaşık 350 ms tut;
tekrar komut için yeniden aç.
Beş parmağın da bükülmüş algılanması gerekir. İki yumruk aynı anda komut üretmez. Sağ yumruk
tutulurken ön plandaki pencere değişirse işlem iptal edilir. Bu özellik tarayıcı içindeki
tek sekmeyi değil, uygulama penceresini küçültür/geri açar. Dry-run yalnız komut metnini
gösterir. Önizleme üstündeki **Sürdür / Duraklat** düğmesinden kontrolü etkinleştirebilirsin.

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
- **Komut bildirimi:** Gönderilen komut kısa bir bildirimle gösterilir (ör. "Sonraki parça"). Ayar: "Kısa durum bildirimlerini göster".
- **Tık sesi:** Tık ve komutta kısa sistem sesi. Varsayılan kapalı (`click_sound`).

## Ayarlar

Tepsiden açılır. Dört sekme vardır:

| Sekme | İçerik |
|---|---|
| Genel | Kamera, ayna görüntüsü, baskın el, varsayılan mod, otomatik duraklat, acil durdurma kısayolu, monitör eşlemesi, katman/bildirim/maskot, Windows ile başlat |
| İmleç | Hassasiyet ön ayarı, imleç türü, hız, hassasiyet, yumuşatma, bekleyerek tıkla ve süresi, tık sesi, imleç halkası |
| Hareketler | Pinch eşikleri, kaydırma ve yakınlaştırma yönü, kaydırma profili (Komutlar) |
| Gelişmiş | Kamera altyapısı, algılama/takip eşikleri, dry-run paneli, ayarları içe/dışa aktar, tanılama raporu |

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

1. Sürüm zip'ini (`Holoscobe-1.0.0-win64.zip`) ve `.sha256` dosyasını indir. Hash'i karşılaştır: `Get-FileHash .\Holoscobe-1.0.0-win64.zip -Algorithm SHA256`.
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

Paket yaklaşık 390 MB açık, 156 MB zip. Sürümü kendin üretmek için: `scripts\release.ps1` (`dist\Holoscobe-<sürüm>-win64.zip` ve `.sha256` üretir). Ayrıntı: [release_packaging.md](Docs/reports/release_packaging.md).

## Kurulum (kaynaktan)

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

Seçenekler: `--live` (gerçek komutlar), `--telemetry` (oturum telemetrisini yerel CSV'ye yazar, görüntü kaydetmez), `--log-level DEBUG|INFO|WARNING|ERROR` (günlük düzeyi, varsayılan `INFO`).

Alternatif: `powershell -ExecutionPolicy Bypass -File scripts\launch.ps1` (dry-run); aynı komuta `--live` eklenebilir. Normal kullanımda `QT_QPA_PLATFORM=offscreen` ayarlı olmamalıdır.

Uygulama Paused başlar. Kamera sağlıklı olduktan sonra tepsiden Sürdür ile veya el çırparak etkinleştirin. Ardından sağ işaret parmağıyla imleci taşıyın, kısa pinch ile tıklayın; diğer hareketler için tepsideki Hareket Rehberi'ne bakın. Tepsiden kamerayı kapatabilir, ayarları/kalibrasyonu açabilir ve çıkabilirsiniz. Kısayol çakışırsa canlı başlatma reddedilir; dry-run ayarlarından başka bir kısayol seçin. Kamera hatası ve kurtarma otomatik etkinleştirme yapmaz. Gerçek donanım kabulü tamamlanana kadar önce dry-run kullanın.

Masaüstündeki `Holoscobe` ve `Holoscobe - Canli` kısayollarını güncel kaynak koduna bağlamak için
`powershell -ExecutionPolicy Bypass -File scripts\update_shortcuts.ps1` çalıştırın.
Bu kısayollar gerçek fare kontrolü ve telemetriyle (`--live --telemetry`) başlatır.

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
  swipe.py         Açık avuç kaydırma tanıyıcısı, Komutlar profilleri
  dwell.py         Bekleyerek tıkla
  controller.py    Durum makinesi, modlar, eylem üretimi
  mapping.py       Kamera alanını iki monitöre eşleme
  safety.py        Eski örnek reddi, bağımsız zaman aşımı gözcüsü
  dryrun.py        Windows'a dokunmayan sahte alıcı
  config.py        Sürümlü ayar dosyası (şema 3)
  diagnostics.py   Tanılama paketi (zip)
  logsetup.py      Döner günlük dosyası, yakalanmamış hata kancaları
  windows/         Win32 bağdaştırıcıları (giriş, pencere, ses, kısayol, oturum, tuş komutları)
  ui/              PySide6 tepsi, önizleme, kalibrasyon, ayarlar, katmanlar
  ui/onboarding.py İlk açılış eğitimi
  tools/           Konsol kabul testi araçları
tests/             Her modülün kendi klasörü
scripts/           Kurulum, test, başlatma, derleme, install/uninstall, release betikleri
packaging/         PyInstaller spec ve giriş noktası
.github/workflows/ CI (ci.yml) ve sürüm (release.yml)
Docs/              Şartname, yol haritası, raporlar
```

Akış: kamera → en yeni kare → takip → özellikler → jestler → denetleyici → eylem → Windows bağdaştırıcısı.

## Benzer araçlardan öğrenilenler

Camera Mouse, eViacam, Project Gameface ve Ultraleap TouchFree incelendi. Bu inceleme şu özelliklerin eklenmesine yön verdi: ilk açılış eğitimi, tutma hareketleri için imleç halkası, kaydırmayla komutlar, bekleyerek tıkla ve hassasiyet ön ayarları. Bu araçlarla başarım karşılaştırması yapılmadı.

## Belgeler

- [Sürüm notları](CHANGELOG.md)
- [1.0 durumu ve elle test listesi](Docs/reports/manager_status.md)
- [Paketleme ve sürüm](Docs/reports/release_packaging.md)
- [Teknik şartname](Docs/Windows_Hand_Gesture_Control_Spec.md)
- [Yol haritası](Docs/ROADMAP_TR.md)
- [Doküman incelemesi ve kararlar](Docs/DOKUMAN_INCELEME_TR.md)
- [Aşama 0 raporu](Docs/reports/phase0_report.md)
- [Üçüncü taraf lisans bildirimleri](THIRD_PARTY_NOTICES.md)

## Bilinen sınırlar

- Tek RGB kamera, başka bir elin arkasında kalan parmağı göremez. Model tahmini ölçüm sayılmaz; kalite düşünce komutlar askıya alınır.
- Yönetici yetkisiyle çalışan uygulamalar ve korumalı Windows ekranları kapsam dışıdır.
- Yakınlaştırma, hedef uygulamanın Ctrl + tekerlek desteğine bağlıdır.
- Komutlar modundaki kısayollar (masaüstü değiştirme, medya tuşları) hedef uygulamanın ve Windows'un o kısayolu desteklemesine bağlıdır.
- Gerçek kamera ve ellerle kabul testi bekliyor.

## Lisans

Projenin kendi kaynak lisansı henüz belirlenmedi. Bu depo özeldir; kamuya dağıtımdan önce lisans netleştirilecektir. Kullanılan üçüncü taraf bileşenlerin lisansları `THIRD_PARTY_NOTICES.md` dosyasındadır.
