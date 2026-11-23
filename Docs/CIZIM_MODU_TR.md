# Canlı kamerada 3B mürekkep

## Yol haritası

Her adım kendi commit'i ve doğrulamasıyla ilerler. Son tamamlanan adımı görmek için `git log --oneline` kullanılabilir.

1. **Plan.** Mevcut el takibini, kamera görüntüsü aktarımını ve mod seçiciyi kullan. Kareyi işleyen kod ile Qt çizimini ayır.
2. **Sahne.** Mürekkebi ortak dikey eksenin yerel uzayında sakla. Her fırça örneğini güncel açının ters dönüşüyle ekle. Küçük bir başlangıç lekesi, değişken kalınlık, sabit sıçramalar ve sarkıntılar üret. Silgiyi ön çalışma düzleminde sınırla. Halka, sarmal ve üst üste gelen katmanları test et.
3. **Hareketler.** Sağ işaretle çiz, sağ açık elle taşı, sağ yumrukla yerel olarak sil. Sol açık avuç tutulduğu sürece sahneyi döndür. Bilek ve dirsekleri izleyerek kısa süre tutulan X'i algıla. El kaybında izi kes. Temizleme boyunca yeni izleri engelle ve alkıştan ayır.
4. **Uygulama.** Çizim modunu mod seçicilere, kamera akışına ve güvenli duraklatmaya bağla. Mürekkebin doğuşunu, silgiyi ve toplu temizleme akışını kameranın üstünde göster.
5. **Doğrulama ve devir.** Hareket, derinlik, mod geçişi ve ekran çizimini otomatik sınamalarla doğrula. Çalıştırma yolunu, sonuçları ve gerçek kamerada denenmesi gereken hareketleri kaydet.

## Kabul senaryosu

Sağ işaret ucuyla iki ayrı noktaya dokunup arada avucu aç. Sol avucu açıp sağa yatır, sağ işareti eksenin sağında sabit tut, sonra yavaşça indir. İlk izin bir bölümünü arkaya döndür, önüne yeni bir iz koy ve yumruğu orada beklet. Arkadaki iz korunmalı. Son olarak ön kolları X yapıp tut. Mürekkep aşağı süzülüp kaybolduktan sonra yeni bir lekeyle başlanabilmeli.

## Durum (2026-11-24)

Beş adımın kodu ve otomatik doğrulaması tamam. İlk gerçek deneme yapıldı; düzeltmeleri aşağıda, ikinci deneme bekliyor.

| Ölçüm | Sonuç |
|---|---|
| Otomatik takım | 1865 geçti, 7 manuel test seçilmedi |
| El + poz izleme (640×480, rastgele görüntü, medyan) | 23,6 ms/kare; yalnız el 11,9 ms |
| Boyama, durağan sahne (1100×680, 5700 leke) | 1,7 ms |
| Boyama, dönen sahne (3470 leke) | 11 ms (önce 22 ms) |
| Boyama, temizleme akışı (3470 leke) | 9-10 ms (önce 91 ms) |

Çalıştırma: `scripts\setup.ps1` (poz modelini indirir), sonra masaüstü kısayolu ya da
`scripts\launch.ps1`; pencerede **Çizim** düğmesi. Sınamalar: `scripts\run_tests.ps1 tests\drawing`.

Kararlar:
- Mürekkep 4000 lekeyle sınırlı; aşılınca en eskisi silinir. Dönerken boyama süresi bununla tutulur.
- X kanıtı birikir (420 ms); kaçan poz kareleri yavaşça düşürür, alkış adayı sıfırlamaz.
- Renk çarkı: sağ elle birleştirip 180 ms tut, dilime götür, ayır. En az iki öbür parmak açık olmalı; yumruk açmaz.
- Mod çarkı (sol V) bu modda da açılır; sol avuç yalnız döndürür.
- Duraklatma ve mod değişimi mürekkebi silmez, yalnız izi keser. Uygulama kapanınca çizim kaybolur.

İlk deneme (2026-11-24) ve düzeltmeler:

| Şikâyet | Neden | Düzeltme |
|---|---|---|
| İstemsiz iz ve silme | Kayıtlı oturumlarda 90 ms'ye kadar süren yanlış pozlar; el açılırken parmak durumu 80 ms geç değişiyor | Araç 100 ms onay ister, ham kıvrıma göre hemen durur, 160 ms'ye kadar kopma izi bölmez |
| Silgi bazen silmiyor | Silgi çalışma düzleminin ±0,009'unu siliyordu; sahne biraz dönünce iz dışarıda kalıyordu | Bütün ön yüzey, sonra yeni yumrukla arka yüzey; silgi büyüdü |
| X tam çalışmıyor | Dirsekler laptop kamerasında görünmüyor; alkış adayı tutmayı sıfırlıyordu | Dirsek yoksa yer değiştirmiş bilekler yeter; biriken kanıt; **Temizle** düğmesi |
| Dönerken takılma | Boyama ve temizleme yavaştı; açı el karelerine bağlıydı | numpy çizici, zamana bağlı yumuşak hız |
| Tek yönlü dönme | Açık avuç yalnız bir yöne döndürüyordu | Avucun yatırıldığı yöne döner |

Gerçek kamerada denenecekler: yukarıdaki kabul senaryosu, ayrıca
1. Fırça, taşıma ve yumruk arasında geçişte istenmeyen iz ya da silme oluyor mu.
2. X hareketi loş ışıkta ve kollu giysiyle algılanıyor mu; alkışla karışıyor mu.
3. Uzun çizimde dönerken görüntü ve el takibi akıcı kalıyor mu.
