> **Geçersiz:** yerini [click_controls.md](click_controls.md) aldı; öne itme tıklaması artık varsayılan olarak kapalı.

# Sağ işaret parmağıyla tıklama

İmleç hareketi ve sol tık, baskın el ayarından bağımsız olarak yalnız sağ elden gelir.
Sol yumrukla son küçültülen pencereyi geri açma ve sağ yumrukla küçültme korunur.

Yeni varsayılan sol tık: başparmak/orta/yüzük/serçe BENT, işaret EXTENDED; 200 ms sabit
pozdan sonra işaret parmağını kameraya doğru kısa ve hızlı itip başlangıç derinliğine
geri getirme. Hareket en fazla 450 ms sürer; tamamlanınca 450 ms tekrar koruması vardır.
Avuç hareketi, poz/kimlik değişimi, duraklatma, takip kaybı, eski örnek, clap adayı ve
mod/menü değişimi hareketi iptal eder. Komut normal epoch/stale-guard/sink yolundan gider.

Algılayıcı uç noktanın avuca göre z değişimini avuç birimiyle değerlendirir; gerçek mesafe
ölçmez. Ham MediaPipe z tahmini gürültülü olabilir. İleri hareket sırasında imleç başlangıç
konumunda tutulur. Eski pinch yolu yalnız açıkça seçilen dahili uyumluluk ayarında kalır;
uygulamanın varsayılanı değildir. Eski regresyon testleri bu ayarı açıkça kullanır.

Gerçek kamera kabulü **bekliyor**. Kullanıcı sağ/sol yumruk komutlarının kendi ortamında
çalıştığını bildirdi; bu, işaret tıklamasının veya diğer donanım kapılarının geçtiği anlamına gelmez.

Elle kontrol: Canlı sürümü yeniden başlat, Sürdür ve İmleç seç. Sağ elde yalnız işareti
açık tut, avuç sabitken parmağı öne/geri hareket ettir: bir sol tık beklenir. Aynı hareketi
sol elde dene: imleç/tık olmamalı. Sağ eli taşı, yavaş it, geri getirmeden tut, takibi
kaybettir: tık olmamalı. Sağ/sol yumrukla küçült/geri aç regresyonunu da kontrol et.

Son offscreen otomatik takım: **695 geçti, 3 manuel test seçilmedi**. Yeni hareket
30/10 FPS sahte örnekleri ve ham işaret noktalarından pipeline testiyle doğrulandı.
