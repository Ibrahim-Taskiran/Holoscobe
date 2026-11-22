# Değişiklik günlüğü

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: [SemVer](https://semver.org/lang/tr/).

Not: Gerçek kamera ve ellerle donanım kabulü her iki sürümde de bir insan tarafından henüz yapılmadı.

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
