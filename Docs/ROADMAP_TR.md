# Holoscobe — Yapım Yol Haritası

Tarih: 12 Kasım 2026 · Dayanak: [v1.1 teknik şartname](Windows_Hand_Gesture_Control_Spec.md)

Hedef: Mevcut HP Victus ve kamerasıyla iki elin on parmağını ayrı takip eden, Windows 11 üzerinde iki monitörü kontrol edebilen, ek yazılım/hizmet ücreti gerektirmeyen ve kurulumdan sonra çevrimdışı çalışan uygulama.

Bu belge uygulama planıdır; yazılımın yapıldığı veya kamera testlerinin geçtiği anlamına gelmez. Başlangıçta bütün aşamalar **bekliyor** durumundadır. Teknik davranış ve kabul ölçütleri için şartname esas alınır; bu plan uygulama sırasını ve teslimleri açıklar.

## Öncelikler ve kapsam

1. İki elde tüm parmakların kimliğini ve bükülmesini güvenilir takip etmek.
2. Yanlış veya eski takip verisinin masaüstünde komut üretmesini engellemek.
3. İmleç, tıklama, kaydırma, yakınlaştırma, ses ve pencere kontrolü.
4. Kolay kurulum, çevrimdışı paket, ayarlar ve anlaşılır geri bildirim.
5. Çekirdek tamamlandıktan sonra isteğe bağlı maskot.

Takipte her el için 21 nokta, toplam 42 nokta kullanılacak. Başparmak, işaret, orta, yüzük ve serçe ayrı isimlendirilecek; her parmak için açık/bükülü/belirsiz durum üretilecek. Her parmağa ayrı Windows komutu atamak gerekmiyor; hepsinin takip edilebilmesi gerekiyor.

Tek RGB kamera, başka bir elin arkasında tamamen kalan parmağı gerçekten göremez. Modelin tahmini kusursuz ölçüm sayılmayacak. Ürün, belgelenmiş ışık/mesafe koşullarında kalite hedefini geçmeli; zor koşullarda yanlış işlem yapmamalı. Ücretli kamera veya servis almak bu planın çözümü değildir.

## Aşama 0 — Ücretsiz teknik temeli doğrula

**Tahmin:** 1–2 iş günü. **Bağımlılık:** Yok.

- Mevcut dosyaları koruyarak proje yapısını oluştur; kamera modeli, işlemci, RAM, Windows sürümü ve ekran düzenini kaydet.
- Python 3.11 x64 aday ortamında MediaPipe Tasks, OpenCV, PySide6 Community, ses bağlayıcıları ve paketleyicinin Windows uyumunu doğrula. Çalışan sürümleri sabitle; gerekirse uyumlu Python sürümünü gerekçesiyle değiştir.
- Yerel el modelini yükleyerek CPU üzerinde örnek çıkarım çalıştır. GPU zorunluluğu oluşturma.
- Bağımlılıkların ve model dosyasının lisanslarını ayrı ayrı kontrol et. Model URL/sürüm, SHA-256 ve dağıtım koşullarını manifestte tut. Modelin lisansı doğrulanmadan pakete ekleme.
- Ücretli SDK, deneme sürümü, API, bulut hizmeti veya zorunlu satın alma olmadığını doğrula. PySide6 için kullanılan modüllerin açık kaynak dağıtım yükümlülüklerini planla.

**Teslim:** Proje iskeleti, bağımlılık kilidi, model manifesti, lisans envanteri ve donanım başlangıç raporu.

**Geçiş kapısı:** Hedef Windows ortamında ücretsiz bileşenlerle yerel çıkarım çalışıyor; seçilen modelin kullanım ve dağıtım koşulları doğrulanmış. Doğrulanmayan konu başarı olarak işaretlenmiyor.

## Aşama 1 — Kamera ve on parmak takibi

**Tahmin:** 4–6 iş günü. **Bağımlılık:** Aşama 0.

- Kamera açma/kapatma, seçim, izin hatası, meşgul kamera ve yeniden bağlanma akışlarını kur.
- Önce 640×480/30 FPS iste; gerçek değeri ölç. Kamera destekliyorsa aynı testleri 1280×720 ile karşılaştır.
- İki el, 42 nokta, sol/sağ el ve on parmağın adları/durumlarını gösteren tanılama önizlemesi oluştur.
- El kimliği eşleştirme, başparmağa özel açı hesabı, avuç ölçeği, histerezis ve takip kalite durumlarını uygula.
- Ayna görüntüsü ile gerçek el kimliğini doğrula. Kalibrasyon sırasında işletim sistemi komutu üretme.
- Sabit el, parmak bükme, eğik el, iki el, el örtüşmesi ve hareket bulanıklığı denemeleri yap.

**Teslim:** Yalnızca kamera/önizleme uygulaması, kalibrasyon profili, karşılaştırmalı çözünürlük ve doğruluk raporu.

**Geçiş kapısı:** Şartname §9'daki 400 sunumluk parmak testi her parmak/durum grubunda en az 19/20; beş dakikalık iki el testinde en az %95 kullanılabilir örnek kapsamı. Bilinmeyen/kayıp sonuçlar doğruluk hesabından çıkarılmaz. Gerçek FPS, örnek yaşı ve gecikme birlikte raporlanır.

**Başarısız olursa:** Önce ışık yönü, kadraj, pozlama, gerçek kamera FPS'si, hareket alanı ve kalibrasyonu düzelt. Sonra ücretsiz profil/model seçeneklerini aynı testle karşılaştır. Kalite hâlâ yetersizse durumu açıkça raporla; eşiği sessizce düşürme ve masaüstü kontrolünü tamamlanmış sayma.

## Aşama 2 — Güvenlik ve komutsuz jest denemesi

**Tahmin:** 3–5 iş günü. **Bağımlılık:** Aşama 1.

- Paused, Active, Calibrating, Fault durumlarını; bağımsız kamera yaşam döngüsünü uygula.
- Tepsi menüsünde duraklat, kamerayı kapat ve çıkışı ekle. Global acil durdurma kısayolunun çakışmasını denetle.
- Takip döngüsü kilitlense bile çalışan zaman aşımı gözcüsü ve bekleyen komutları iptal mekanizması kur.
- El çırpma, pinch, parmakla gösterme, mod menüsü ve nötr duruma dönüşü zaman damgalı örneklerle sınayıp gerçek kamerada ayarla.
- Ekranda yalnızca “üretilecek komut” göster; Windows'a giriş gönderme. Jest çakışmalarını bu aşamada çöz.

**Teslim:** Dry-run modu, durum makinesi, sahte komut alıcısı ve kritik mantık testleri.

**Geçiş kapısı:** 20 kasıtlı el çırpmanın en az 18'i algılanıyor ve her biri tek geçiş üretiyor. Beş dakika olağan kullanımda yanlış etkinleştirme yok. 150 ms'den eski örnek eyleme dönüşmüyor; 200 ms içinde etkileşim iptal ediliyor. Kamera durması, oturum kilidi ve acil durdurma testleri geçiyor.

## Aşama 3 — İmleç ve tıklama

**Tahmin:** 2–4 iş günü. **Bağımlılık:** Aşama 2.

- İki ekranın fiziksel koordinatlarını ve DPI ölçeklerini oku; kalibre edilen alanı masaüstüne eşleştir.
- One Euro benzeri zamana duyarlı filtre ile titremeyi azalt; filtreyi gerçek gecikmeyi ölçerek ayarla.
- Pinch başlangıcında tıklama konumunu sabitle. Hareket/süre eşiği aşılırsa tıklamayı iptal et.
- Negatif koordinat, ekranlar arası boşluk ve farklı ekran yüksekliklerini dene.

**Teslim:** Güvenli pointer modu, kalibrasyon ekranı ve gerçek donanım ölçüm raporu.

**Geçiş kapısı:** Her iki ekranın köşelerine erişim; 20 amaçlı tıklamada en az 18 başarı; yalnızca imleç hareketinde sıfır yanlış tıklama. Normal kullanımda en az 20 işlenmiş kare/sn ve yazılımsal capture-to-action p95 gecikmesi 150 ms altında. Sabit el titremesi ayrıca ölçülür.

## Aşama 4 — Kaydırma, yakınlaştırma ve ses

**Tahmin:** 2–3 iş günü. **Bağımlılık:** Aşama 3.

- Mod menüsünü gerçek işlevlere bağla; menü açıkken Windows komutlarını dondur.
- Kaydırmada artık hareket biriktirme, ölü bölge ve hız sınırı uygula.
- Yakınlaştırmada iki pinch için başlangıç penceresi kullan; el çırpmayla çakışmasını engelle. Tek el bırakıldığında durdur.
- Tekerlek komutlarında hedef pencere/odak değişirse işlemi iptal et. Ctrl temizliğini başarısız komutlarda da doğrula.
- Ses seviyesini mevcut çıkış aygıtından başlat, %0–100 arasında tut; aygıt değişiminde yeniden bağlan.

**Teslim:** Scroll, Zoom ve Volume modları; uygulama uyumluluk tablosu.

**Geçiş kapısı:** Edge veya Chrome'da zoom doğrulanmış; yanlış hedefe tekerlek komutu, takılı Ctrl ve ses sınırı aşımı yok. Kimlik kaybı ve el bırakma sonrası kendiliğinden yeniden başlama yok.

## Aşama 5 — Pencere ve iki monitör kontrolü

**Tahmin:** 3–5 iş günü. **Bağımlılık:** Aşama 4.

- Pencere hedefini HWND ve süreç kimliğiyle sabitle; her işlemde yeniden doğrula.
- Kısa pinch ile pencere eylem menüsü, 250 ms tutuşla sürükleme davranışını ayır.
- Küçült, büyüt/geri yükle, diğer monitöre taşı ve kapat eylemlerini ekle. Kapatma için bırakıp yeniden 1 saniye tutma onayı iste.
- Büyütülmüş pencereyi sürükleme, farklı DPI ve ekrandan taşmayı yönet.
- Kaydedilmemiş belgeyi kapatırken uygulamanın kendi uyarısını koru; süreç sonlandırma kullanma.

**Teslim:** Windows modu ve çoklu ekran test raporu.

**Geçiş kapısı:** Şartname §9 ekran/pencere testleri geçiyor. Tarayıcı sekmeleri aynı pencerede kalıyor; geçersiz hedef başka pencereye işlem yapılmasına yol açmıyor. Yükseltilmiş uygulamalar destek dışı olarak bildirilip geçiliyor.

## Aşama 6 — Sağlamlaştırma ve ücretsiz çevrimdışı dağıtım

**Tahmin:** 3–5 iş günü. **Bağımlılık:** Aşama 5.

- Sürümlü ayar dosyası, bozuk ayardan kurtarma, dönen yerel loglar ve isteğe bağlı Windows başlangıcını tamamla.
- Model hash kontrolü yapan kurulum, başlatma, test ve paketleme PowerShell betiklerini hazırla.
- PyInstaller one-folder paketi üret; gerekli yerel kütüphaneleri ve Qt eklentilerini dahil et.
- Üçüncü taraf bildirimleri ve gerekli lisans/kaynak erişim bilgilerini ekle. Kamuya dağıtım öncesinde proje kaynak lisansını netleştir.
- Temiz Windows kullanıcı hesabında, boşluk/Türkçe karakter içeren yolda ve internet kapalıyken paketi dene.
- En az 30 dakika kullanımda kilitlenme, takılı giriş, kaynak artışı ve beklenmeyen komutları izle; sonra kritik kabul testlerini tekrar çalıştır.

**Teslim:** Çalıştırılabilir kaynak proje, sürüm kilidi, betikler, çevrimdışı uygulama klasörü, Türkçe kullanım kılavuzu, jest özeti, lisans dosyaları ve kabul raporu.

**Geçiş kapısı:** Şartnamedeki tüm zorunlu kontroller geçti; bekleyen donanım testi yok. Hesap, API anahtarı, abonelik ve ücretli araç olmadan paket çalışıyor. İnternet kapalıyken kamera ve tüm çekirdek kontroller kullanılabiliyor.

## Aşama 7 — İsteğe bağlı maskot

**Tahmin:** Basit yer tutucu için 2–4 iş günü. **Bağımlılık:** Çekirdek sürüm kabul edilmiş.

- Önce uygulamada üretilen basit karakter kullan; ek varlık satın alma.
- El hareketi ve parmak bükülmesini yansıt, takip kaybında nötr poza dön.
- Tıklamaları engellemeyen ve pencere hedefi sayılmayan katman oluştur; tepsiden kapatılabilsin.
- GLB/glTF yükleme ve kemik eşleştirme sonraki geliştirmedir; ücretsiz renderer ve varlık lisansı doğrulanmadan teslim sözü verme.

**Geçiş kapısı:** Maskot açıkken de doğruluk/FPS/gecikme hedefleri geçiyor. Renderer hatası veya eksik model masaüstü kontrolünü durdurmuyor.

## Süre ve uygulama sırası

Tek geliştirici ve gerçek laptopa düzenli erişim varsayımıyla çekirdek yaklaşık **18–30 iş günü**, basit maskot **2–4 ek iş günü**. Bunlar planlama tahminidir; kamera kalitesi, uyumluluk ve gerçek test başarısızlıkları süreyi artırabilir. Parmak doğruluğu sağlanmadan takvim uğruna sonraki aşamaya geçilmez.

Sıra: ücretsiz temel → on parmak doğruluğu → acil durdurma ve dry-run → imleç → diğer kontroller → pencereler → çevrimdışı paket → maskot.

İlk çalışan prototip Aşama 1 sonunda kamera önizlemesidir. İlk masaüstü kontrolü Aşama 3 sonunda gelir. Tam çekirdek sürüm Aşama 6 sonunda kabul edilir.

## Test raporu şablonu

Her geçiş kapısı için aşağıdaki kayıt tutulmalı:

| Alan | Kaydedilecek bilgi |
|---|---|
| Ortam | Laptop/CPU, Windows, kamera, çözünürlük/FPS, ekran/DPI düzeni |
| Yazılım | Uygulama revizyonu, bağımlılık sürümleri, model SHA-256 |
| Koşul | Işık, arka plan, el mesafesi, görünürlük, kalibrasyon profili |
| Deney | Poz/jest, tekrar sayısı, elle verilen doğru etiket, ölçüm yöntemi |
| Sonuç | Başarılı/hatalı/belirsiz/kayıp sayıları, oran ve gecikme |
| Karar | Geçti / kaldı / yapılmadı; hata ve yeniden test bilgisi |

Ayar yapılan denemeler ile son kabul denemeleri farklı diziler olmalı. Sentetik test sonucu kamera başarısı olarak raporlanmamalı. Normal kullanımda görüntü kaydı tutulmaz; değerlendirme kaydı ancak açık kullanıcı izniyle, yerelde ve silinebilir biçimde yapılır.
