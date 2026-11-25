# Değişiklik günlüğü

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: [SemVer](https://semver.org/lang/tr/).

Not: Gerçek kamera ve ellerle donanım kabulü her iki sürümde de bir insan tarafından henüz yapılmadı.

## [Unreleased]

### Added
- 3B tüylü kedi maskot (`handcontrol/mascot/`): masaüstü modlarında ekranın sağ alt köşesinde tıklama geçiren, odak çalmayan şeffaf pencere. Yüz (baş dönüşü, bakış, göz kırpma, çene, gülümseme, kaş), kol ve patileri gerçek zamanlı taklit eder; kimse yokken fareyi izler, imleç üstüne gelince yarı saydamlaşır; Enstrüman ve Çizim modlarında gizlenir. OpenGL 3.3 ile çizilir. `face_landmarker.task` modeli, `assets/mascot/` varlıkları, `scripts/cat_model.py` ve `scripts/build_mascot.py` eklendi. Model proje sahibinin kendi gri kedisidir; üçüncü taraf atfı gerektirmez.
- **Kontrol başlayınca ana pencereyi küçült** ayarı (`hide_on_control`, varsayılan açık): canlı masaüstü kontrolü başlayınca kamera penceresi küçülür, kedi sağ altta kalır.
- Çizim: sağ elle başparmak-işaret birleştirilip tutulunca renk çarkı (8 renk); ayırınca seçilir.
- Mod çarkı: sol elle V yarım saniye tutulunca açılır, V ile yönelinir, yumrukla seçilir. Her modda çalışır. Açık avuçla açılan eski mod menüsünün yerini aldı.
- Üst çubuk sadeleşti (İmleç, Kaydırma, Enstrüman, Çizim, Diğer); alttaki ipucu seçili moda göre değişir.
- Çizim modu: kamera görüntüsünün üstünde dönen 3B mürekkep. Sağ işaret çizer, sağ avuç taşır, sağ yumruk siler, sağa ya da sola yatırılan sol avuç o yöne döndürür, X yapılan ön kollar hepsini akıtarak temizler. Windows'a komut göndermez. X için MediaPipe Pose Landmarker Lite modeli eklendi.
- Enstrüman: "Serbest teller" düzeni. Kullanıcı telleri kendisi çizer: çimdikle-tut-çek ile yeni tel, uçtan tutup boyutlandırma ve döndürme, ortadan tutup taşıma, iki elle iki ucu tutma, kısaltıp bırakınca silme (en çok 10 tel). Fareyle de aynı düzenleme; sağ tık siler, Delete hepsini siler. Teller ayarlarda saklanır.
- İsteğe bağlı hizalama yardımı (varsayılan açık): yakın getirilen tel yataya/dikeye düzleşir, paralel telin üstüne aynı uçlarla ve mevcut aralıkla oturur. Uzaktaki tele dokunmaz; kapatılabilir.

- Tek ana pencere (`ui/main_window.py`): mod düğmeleri, durum, kamera görüntüsü; Enstrüman aynı pencerede sayfa olarak açılır. Araç çubuğundan düzen, tel silme, hizalama, tel sayısı, tını ve ses anında değişir.
- `scripts/holoscobe.pyw`: konsolsuz kaynak başlatıcı; masaüstü kısayolu artık eskimiyor.

### Performance
- Tek el görünürken izleme tek el modeliyle yapılıyor (`adaptive_hands.py`): gerçek modelle, sentetik karede kare başına 29 ms yerine 14 ms. İkinci el ayrı bir iş parçacığında 125 ms aralıkla aranıyor; ortalama 5 karede (eskiden 1) fark ediliyor. Yakınlaştırma ve Enstrüman modlarında iki el modeli her karede çalışmayı sürdürüyor.
- Kontrol duraklatılmışken ve 2 saniyedir el görünmüyorken izleme 30 yerine 10 FPS çalışıyor (tek çekirdekte ölçülen yük %57 yerine %27, etkin kontrole göre); el görünen ilk karede tam hıza dönüyor.
- BGR-RGB çevirme `cv2.cvtColor` ile yapılıyor.

### Changed
- Modern koyu grafit ve kayısı arayüz yenilemesi (`ui/theme.py`, `ui/widgets.py`, `ui/icons.py`, `ui/illustrations.py`): solda mod şeridi (mode rail), üstte durum/Ayrıntı/Kedi/Sürdür başlık çubuğu, sol kenar çubuklu ve kart tabanlı 5 kategorili Ayarlar penceresi, yenilenen eğitim, kalibrasyon, tepsi ve katman tasarımı.
- Enstrümanın varsayılan düzeni "Serbest teller" oldu.
- Enstrüman modunu düğme ya da tepsiden seçmek onu hemen başlatır (kamera kapalıysa açar); bu mod Windows'a komut göndermez.
- Ses cihazı hatası artık modu kapatmıyor: teller ekranda kalır, ses 3 saniyede bir yeniden denenir.
- Kamera görüntüsü gerilmeden, kendi oranında çizilir.
- Masaüstü kısayolu tek ve `--live`.
- Maskot modeli değişti: Fripouille (CC BY 4.0) yerine proje sahibinin gri kedisi. Kabuk kürk yerine gerçek tüy geometrisi, göz küresi etrafında dönen kapaklar; uygulama simgesi (`assets/icon.ico`) ve arayüz kedisi aynı renklere geçti.

### Fixed
- "Sürdür" düğmesi ve tepsi öğesi tek tıkta hem sürdürüp hem duraklatıyordu (kontrol duraklatılmış kalıyor, pencere yine de küçülüyordu); kamera düğmesi de açtığı kamerayı hemen kapatıyordu.
- Maskot: kol kalkınca dirsek ve bilekte oluşan boğum giderildi; kol mesh'i yarı açık pozda üretiliyor.
- Masaüstü kısayolu yeni simgeye geçmiyordu (Windows simge önbelleği); `update_shortcuts.ps1` her simgeye ayrı yol veriyor.
- Kamera ilk açılışta ve ayar kaydında ~11 saniye bekletiyordu (MSMF donanım dönüşümleri); 0,6 saniyeye indi. Bu sürede teller görünmüyordu.
- Kayıtlı teller ilk kamera karesini beklemeden çiziliyor.
- Varsayılan mod Enstrüman iken ana pencereden önce ayrı bir pencere açılıyordu.
- Serbest teller: kısa takip kayıpları (250 ms'ye kadar), titrek kare ve el kimliği değişimi çizimi bölmüyor; çimdikliyken mod menüsü açılmıyor.
- Ses düzeyi ya da tını değişince çalan notalar kesilmiyor.
- Sabit teller: iki elle taşınan alan mod değişiminde eski yerine dönmüyor.

## [1.1.0] - 2026-11-22

### Added
- Enstrüman modu (yedinci mod, `Mode.INSTRUMENT`): sol elin başparmak ve işaret ucu arasına sanal gitar teli; sağ işaret parmağıyla vurunca gerçek zamanlı gitar sesi. Windows'a hiçbir giriş komutu gitmez; dry-run'da da çalışır.
- Solo düzen (1 tel, uzunluk = perde, Mi minör pentatonik 2 oktav, diziye kilitli ya da kesintisiz, ±2 yarım ton perde bükme) ve Akor düzeni (4 paralel tel, 4 dikey bölgeden akor, aşağı/yukarı strum, teller arasında ms aralık).
- Saf, deterministik motor (`instrument/geometry.py`, `strings.py`, `music.py`, `engine.py`, `session.py`): iki kare arası süpürülen parça ile tel kesişimi, tel başına 60 ms bekleme ve histerezis bandı, hız → şiddet, kalite/kimlik/takip kaybında yeni nota yok.
- Ses motoru (`instrument/synth.py`): numpy ile vektörize genişletilmiş Karplus-Strong (Jaffe-Smith), 8 ses polifoni, ses çalma, Temiz/Elektro tını, −3 dBFS limiter.
- Ses çıkışı (`instrument/audio.py`): sounddevice, WASAPI öncelikli (DirectSound, MME yedek), 48 kHz, 128/256 örnek blok, kilitsiz kuyruk; cihaz hatasında Türkçe bildirim ve güvenli mod kapatma.
- Enstrüman penceresi (`ui/instrument_view.py`): kamera görüntüsü, el iskeleti, parlayan ve titreşen teller, sınırlı kıvılcım parçacıkları, nota/akor göstergesi. Tepside "Enstrüman" modu ve "Enstrüman penceresi".
- Ayarlar "Enstrüman" sekmesi (ses cihazı listesi, Test sesi çal). Ayar şeması 4 (eski dosyalar kayıpsız taşınır).
- Sabit teller düzeni: 3-8 yatay tel ekranda sabit durur, iki elin işaret parmağı da çalar. Tel alanı Enstrüman penceresinde fareyle taşınır/köşeden boyutlandırılır ya da iki elle çimdikleyip 400 ms tutarak gerdirilir; yeni alan kaydedilir.
- Enstrüman modunda daha sıkı jestler: el çırpma iki elde 4 parmak açıkken, mod menüsü 5 parmak açık ve el sabitken.
- `--self-test` ve paketleme denetimi ses kütüphanesini (PortAudio) doğrular; pakete yalnız `libportaudio64bit.dll` girer.
- Otomatik test takımı 1769 teste çıktı (7 manuel test seçilmez).

### Fixed
- Enstrüman modundayken ayarları kaydetmek kamerayı durduruyor ve modu varsayılana döndürüyordu (Elektro tını seçimi çökme gibi görünüyordu). Kamera artık yeniden başlar, Enstrüman modunda kalınır.

### Changed
- Mod menüsü 7 satır oldu; satır konumu sabitleyen 2 test bu yüzden güncellendi.
- `sounddevice` doğrudan bağımlılık oldu (sürüm ve hash'ler değişmedi).

## [1.0.0] - 2026-11-18

### Added
- Komutlar modu (altıncı mod): açık avuçla sola/sağa/yukarı/aşağı kaydırma ve kısa pinch ile klavye ve medya tuşu gönderme (`swipe.py`, `windows/` tuş komutları).
- Uygulama profilleri: `swipe_profile` (`auto`, `slides`, `browser`, `media`, `desktops`). `auto` ön plandaki uygulamanın exe adından profil seçer.
- İlk açılış eğitimi (`ui/onboarding.py`): sekiz adım, büyük pratik hedefleri, Atla düğmesi, bir kez açılır.
- İmleç halkası: basılı tutma hareketlerinde ilerleme gösterir.
- Komut bildirimi ve isteğe bağlı tık sesi.
- Bekleyerek tıkla (`dwell.py`, `dwell_click`, `dwell_ms`).
- Otomatik duraklatma (`auto_pause_s`): kullanılabilir el görünmezse kontrol duraklar.
- Sekmeli ayarlar penceresi (Genel, İmleç, Hareketler, Gelişmiş), hassasiyet ön ayarları (Hassas, Normal, Hızlı, Özel), ayarları içe/dışa aktarma.
- Tanılama paketi (`diagnostics.py`): günlükler ve sistem bilgisi tek zip, Masaüstüne yazılır.
- Dosyaya günlükleme (`logsetup.py`): `%LOCALAPPDATA%\Holoscobe\logs\holoscobe.log`, döner, `--log-level`.
- Tek örnek koruması: ikinci çalıştırma "Holoscobe zaten çalışıyor" der.
- Ayar şeması 3; eski ayar dosyaları otomatik taşınır (mevcut kullanıcıda eğitim atlanır).
- Hazır paket: PyInstaller onedir derleme (`scripts\build.ps1`), kendini sınama (`--self-test`), `scripts\release.ps1` (zip + `.sha256`), yönetici gerektirmeyen `scripts\install.ps1` ve `scripts\uninstall.ps1`.
- CI ve sürüm iş akışları: `.github/workflows/ci.yml`, `.github/workflows/release.yml`.
- El modeli SHA-256 yeniden doğrulaması kaydedildi; sürümde paketlemeye izin verildi.
- Otomatik test takımı 1455 teste çıktı (3 manuel test seçilmez).

### Changed
- Komut rehberi artık `swipe.py` profil tablolarından üretilir; belge ile kod ayrışmaz.
- Eğitim yalnız ilk açılışta bir kez açılır.
- README, 1.0 durumuna göre yeniden yazıldı (eğitim, Komutlar, ayarlar, kurulum, sorun giderme).
- Bilinen kısıt: exe imzasız; SmartScreen uyarısı verebilir. Projenin kendi lisansı henüz belirlenmedi.

### Fixed
- İmleç halkası katmanı uygulamaya bağlandı.
- Eğitim penceresinin her açılışta tekrar çıkması giderildi.
- Dahili kamera gereksinimi ve tıklama donanım raporları belgelendi.

## [0.1.0] - 2026-11-12 (iç sürüm, 2026-11-15'e kadar geliştirme)

### Added
- Proje iskeleti, ortak sözleşmeler (`contracts.py`) ve sahiplik kuralları.
- Faz 0 temeli: kamera yaşam döngüsü, MediaPipe takip, ayar dosyası, on parmak özellikleri, pinch ve el çırpma tanıyıcıları.
- Denetleyici durum makinesi, güvenlik koruması ve bağımsız zaman aşımı gözcüsü, dry-run alıcı, iki monitör eşlemesi.
- Win32 bağdaştırıcıları (giriş, pencere, ses, kısayol, oturum) ve konsol kabul testi araçları.
- PySide6 arayüzü: tepsi, önizleme, kalibrasyon, ayarlar, katmanlar, geri bildirim.
- Uçtan uca boru hattı ve `handcontrol.app` girişi; varsayılan dry-run, gerçek komutlar yalnız `--live`.
- İşaretçi: göreli imleç (debriyaj ve ivme), sol tık, çift tık, uzun basma sağ tık, sağ tık pinch'i, sürükle bırak (hareketle ve üç parmak kavrama).
- Yumruk tutma ile pencere küçültme ve geri açma.
- Windows ile başlatma kaydı, tıklama kaydedici ve imleç izleme araçları.
- Yapışkan imleç, toleranslı takip, telemetri ve durum göstergesi.
- README.

### Changed
- Tıklama, "işaret parmağını ileri itme"den pinch hareketlerine taşındı; eski itme tıklaması varsayılan kapalı.
- Mutlak imleç yerine göreli imleç varsayılan oldu.

### Fixed
- Pinch tarafı çözümü ve güvenli tıklama oturumlarının korunması.
- Kısa parmak geometrisi boşluklarında hareketin korunması.
- Ayarlar penceresindeki değer hatası.
