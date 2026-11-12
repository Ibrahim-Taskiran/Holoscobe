# Tıklama ayarı — 4. tur geçici devir

2026-11-12. Push yapılmaz; dokunulmayan kaynak kayıt:
`hw_click_20261112-152708-382361.csv`, **5914 veri satırı**,
SHA-256 `eb26b0f8ba5f052ea93642af33a07d65f3a352327d8472d276c178f635fc97e4`.

Devralınan tek yarım dosya `controller.py` idi (158 ekleme / 65 silme); tıklama testleri 24 hata veriyordu.
Karar penceresi ve aynı kimlikte kısa DEGRADED toleransı korundu. Otomatik sağ eşitlik tercihi, her
sağ tıkı 600 ms bastırma ve sol sürüklemeyi 0,60'a çıkarma tamamlanmamış yaklaşımları düzeltildi.
Kendi salımının yeniden kurma kaydına takılan kısa tık ve iki kare arasında 480 ms'yi aşınca kaybolan
sol eylem de düzeltildi. Git checkout/reset kullanılmadı.

Ölçüm: 5403 ok, 333 degraded, 80 ambiguous, 98 missing kare. Sol tekrar minimumları **0,030–0,126**,
sol temas sırasında orta uzaklığının minimumu **0,623**. Sağ minimumlar **0,060–0,136**; 10 sağ tekrarın
6'sında işaret de 0,33 altına iniyor. Açık referans medyanı sol **1,026**, sağ **1,012**. Still/range'de
orta mesafesi medyan **0,336 / 0,333**, range minimumu **0,023**: işaret pozu koruması zorunlu.
Sol 8'in temas karelerinde işaret hep EXTENDED; sağ 6'da çoğunlukla iki parmak da BENT: yalnız duruma
veya yalnız bir mesafeye güvenilemez. Yumrukta beş BENT oranı tüm kullanılabilir tekrar karelerinde
**%28,8–81,9**; yalnız action bölümünde **%6,2–96,6**. Kayıt, kıvrım skorunu içermiyor.

| Kural | Eski → yeni | Gerekçe |
|---|---|---|
| Sol/sağ karar | Anlık/mesafe → **60 ms** pencere, son kesin parmak oyu öncelikli | Orta BENT + işaret EXTENDED sağ; tersi sol. Sonra taraf kilitlenir; diğer temas iki kanal salınana kadar eylem başlatmaz. |
| Mesafe marjı | **0,08 → 0,02** | Sağda iki uzaklık birbirine yaklaşıyor. Durum kararsızsa belirgin küçük mesafe kazanır; marj içindeki iki temas kararsız bırakılır, yanlış sola dönmez. |
| Yeniden kurma açıklığı / dar tekrar penceresi | **0,60 / 300 ms → 0,90 / 700 ms** | Sol 1'de dar açılma tepe değerleri 0,899 / 0,776 ve aralar 562 / 640 ms; sağ 3'te 296 ms ve 0,785. Belirgin açılma hemen yeniden kurar, bilinçli çift tık korunur. |
| Sağ hareket iptali | Sol ile ortak **0,45 → ayrı 0,60** | Sağ 6'nın kayıttaki son temas→salım örneklerinde yaklaşık **0,497** avuç hareketi var. Sol sürükleme sınırı **0,45** kalır. |
| Aynı-ID DEGRADED kopması | Anında iptal → son kullanılabilir yakalamadan **200 ms'den az** süre donma | Geçersiz kare eylem üretmez/watchdog'u beslemez; dönüşte göreli hareket yeniden çapalanır. Tam 200 ms'de bırakma devam eder. |
| Korunan değerler | Pinch **0,33/0,48**, tutma **480 ms**, curl **0,80**, debriyaj pozu değişmedi | Mesafeler pinch ayrımını destekliyor; uzun yönergeli tutuşlar doğal tık süresi değil. Curl kayıtta yok. İşaret pozunda en az iki kıvrık orta/yüzük/serçe şartı gözlemle uyumlu. |

Kopma ölçüsü son iyi kareden bir sonraki iyi kareye süredir; tekrar sınırları birbirine bağlanmadı:

| Aşama | Tam boşluk | <200 ms | Medyan / p95 / en uzun ms |
|---|---:|---:|---|
| Gezdirme | 1 | 0 | 672 / 672 / 672 |
| Sol pinch | 7 | 4 | 109 / 3312 / 3312 |
| Sağ pinch | 9 | 4 | 312 / 1031 / 1031 |
| Sürükleme | 8 | 1 | 757,5 / 1750 / 1750 |
| Yumruk | 13 | 13 | 78 / 172 / 172 |

Toplam **38** tam boşluğun **22**'si 200 ms altı; medyan **132,5**, maksimum **3312 ms**. Sonu görünmeyen
ayrı boşluklar: sol 6 **en az 610 ms**, sürükleme 2 **en az 625 ms**, yumruk 2 **en az 32 ms**.
Sol 7'de **126/177** kötü kare; sürüklemelerde **54, 69, 47, 50, 0**. Uzun boşlukların korunması güvenli
değildir. Missing, kimlik belirsizliği/değişimi ve eski kareler anında iptal etmeyi sürdürür. Eylem
yakalama yaşı **150 ms**, watchdog **200 ms** korunmuştur. Ölçüm betiği `tests/controller/click_record_analysis.py`.

Sektirme ayrımı sınırlı: bazı sağ ön temaslarda 1,2–1,34 sn ve tamamen açık aralar da var; bunların aynı
fiziksel pinch olduğu kayıttan kanıtlanamaz. 700 ms kuralı yalnız dar açılmayı birleştirir, tüm sağ
tıklamaları süreyle engellemez. 70 ms debounce'tan kısa temaslar zaten başlangıç oluşturmaz.

Tekrar verisi: `tests/controller/data/click_record_excerpt.csv` **728 değiştirilmemiş satır**, kaynak satır
indeksleri/hash JSON manifestinde. Sol 1/8, sağ 2/6/8, sürükleme 3/5 seçildi. Asıl zamanlı tekrar sol 1'de
tek sol tıkı ve sürükleme/uzun kopmada bırakmayı doğrular. Kısa tık sınıflandırması için dört açık + altı
son temas + dört salım karesi **33,4 ms yapay aralıkla** oynatılır: sağ örneklerin her biri tam bir RIGHT_CLICK,
hiç sol eylem; sol örnekler sol etkinlik ve sıfır RIGHT_CLICK üretir. Çok saniyelik tutuş bu testte
kırpılmıştır; bu doğal süre/başlangıç gecikmesi ölçümü değildir. Özgün zamanlı uzun sağ tutuşlar hâlâ
iptal edilir ve sola dönüşmez. Tam CSV'nin 10 sağ tekrarının asıl zamanlı incelemesinde sol eylem görülmedi.
Landmark 4/8/12 ölçülmüş iki mesafeyle tutarlı üretilir, parmak durumları CSV'den alınır; curl sentetiktir,
FeatureExtractor veya 0,80 curl sınırının donanım doğrulaması sayılmaz.

Test uyarlamaları: taraf kilidinden sonra diğer pinch'i iptal sayan eski vaka yeni kilit davranışını;
eşit/kararsız mesafede otomatik solu bekleyen vaka artık sıfır eylemi; DEGRADED iptal vakası da tam 200 ms
bırakmayı doğrular. Test silinmedi; çift tık, uzun sağ tutuş iptali ve kimlik/güvenlik kontrolleri korundu.
Hedefli tur: **235 geçti, 282 seçilmedi**; son çift tık düzeltmesinin seçili turu **194 geçti**.
Son tam takım: **1072 geçti, 0 başarısız, 3 seçilmedi**, **11,42 s**; istenen offscreen / PYTHONPATH=src /
`pytest -q -p no:cacheprovider` ile. İlk tam denemede varsayılan pytest geçici dizinine sandbox erişimi
engellendi (63 kurulum hatası); izinli tekrar temiz geçti. İlk denemenin iki gerçek çift tık hatası da
işaret pozundaki doğal orta temasının oturumu kilitlemesiydi; korumalı işaret pozu bu kilide sayılmaz.

Commit özeti: `fix(pointer): resolve pinch side and preserve safe click sessions`. Yalnız ilgili controller,
testler, kırpılmış test verisi ve bu rapor dahil edilir; `.claude/`, `CLAUDE.md`, tam `hw_*` kayıtları hariçtir.

Kullanıcı: sol tıkta işaretin BENT görünmesi artık engel değil. Sağ tıkta yüzük ve serçeyi ikisini birden
kıvırmayın; işaret pozundan sağ tıka geçerken onları açın. Kısa tıkı **480 ms altında bırakın**; uzun sol tutuş
sürüklemedir, uzun sağ tutuş iptal olur. Bilinçli çift tıkta parmakları belirgin açın (yaklaşık 0,90 avuç).
Kalan iş: yeni gerçek kamera denemesi; özellikle sağa geçişte parmak latch gecikmesi ve kısa temaslar,
farklı ışık/mesafe, >200 ms kopmayı azaltacak takip kalitesi. Uzun kopmalar için güvenlik gevşetilmedi.
