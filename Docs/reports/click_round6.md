# Tıklama turu 6 (oturum 2026-11-14 21:52, 270 sn, işaretçi kipi)

## Ölçüm: başparmak+işaret (54 PINCH_START, 84 ham dalış)
| Sonuç | Adet | Tutma medyanı (ms) | Aralık (ms) | Avuç yolu medyanı (pu) |
|---|---|---|---|---|
| Sol tık | 18 | 266 | 140-469 | 0.08 (en çok 0.16) |
| Sürükleme (480 ms zamanla) | 14 | 2656 | 531-7688 | 0.44 |
| İptal (gerekçeli) | 13 | 1140 | 188-1938 | 0.38 |
| Sessiz | 9 | 547 | 47-1750 | 0.07 |
- 14 sürüklemenin 14'ü de süreyle başladı (LEFT_DOWN 469-532 ms). 4'ü LEFT_DOWN-LEFT_UP arası 0.15 pu altında (hareketsiz el), 5'i 0.25 altında. Gerçek sürüklemeler 1.15-3.30 pu yol aldı; durağan elde kayma en çok 0.39 (bir tanesi 0.49).
- "Önce parmakları açın" 6 kıstırmayı kesti: aralık 125-531 ms, açılma 0.53-0.78 pu. Çift tık yok sebebi bu kural (yeniden kurma 0.9 pu ya da 700 ms istiyordu).
- Sessiz 9: menü açık 3, sol el 2, yumruk 2, yeniden kurma (aynı metin tekrarı) 2.
- PINCH_START olmayan 29 dalış: çoğu 1-2 karelik (< 70 ms debounce) ya da işaret pozunda; gestures.py katmanı, denetleyici değil.

## Ölçüm: sağ tık (başparmak+orta, 14 deneme)
| Sonuç | Adet | Not |
|---|---|---|
| Sağ tık | 5 | açık el, 2-10 kare |
| "uzun tutuldu" | 3 | açık el, toplam temas 1.6 / 1.7 / 2.8 sn |
| "el duruşu uygun değil" | 4 | 4'ünde de 125-140 ms içinde işaret pozu + imleç hareketi |
| "parmaklar büküldü" | 3 | 3'ünde de hemen işaret pozu; biri DEGRADED/kayıpla bitti |
Sonuç: duruş vetoları doğru çalıştı (işaret pozunu korudu); asıl kayıp uzun tutma iptali.

## Kural değişiklikleri (eski -> yeni)
- Sürükleme: 480 ms tutma -> yalnız avuç yolu > 0.6 pu (eski 0.45). Gerekçe: durağan kayma ≤ 0.49, gerçek sürükleme ≥ 1.15.
- Sol tık: < 480 ms -> ≤ 1500 ms (`tap_max_ms`); daha uzun: "Tıklama iptal: uzun tutuldu". Tahmin: 14 sürüklemeden 4'ü tık, 4'ü iptal, 6'sı sürükleme olurdu.
- Çift tık: tıktan 250-500 ms sonra aynı yerde ikinci kıstırma geniş açılma istemeden kurulur (`double_tap_min_gap_ms`). Gerekçe: ikinci dokunuşlar 281-485 ms, titreme 125-140 ms.
- Sağ tık süresi: 480 ms -> 3000 ms (`right_hold_max_ms`). Gerekçe: iptal edilen 3 gerçek tutma 1.6-2.8 sn.
- Sağ tık bükülme: tek bükük kare iptal -> 150 ms süren bükülme ya da bükük bırakma karesi iptal (`right_curl_cancel_ms`). Duruş kararı başlangıç karesinde (ya da karar anında) verilir.
- Kısa DEGRADED aralık: boştayken de (etkileşim yokken) aynı el < 200 ms atlanır; kapanmakta olan sağ kıstırma sıfırlanmaz. Başlamış sağ tık zaten korunuyordu.
- Görünürlük: nötr beklenirken ya da yumrukta reddedilen kıstırma `last_cancel` yazar; belirsiz parmakla reddedilen sağ başlangıç da.

## Doğrulanmadı (sonraki kamera oturumu)
- Başparmak-orta mesafesi kayıtta yok; sağ tık sayıları duruma ve bildirime dayalı.
- 0.6 pu eşiği küçük, yavaş sürüklemeleri geciktirir (kayıtlı sürükleme 5: 4.5 sn'de 0.31 pu artık sürükleme değil).
- Çift tıkta Windows süresi: ikinci tık bırakmada gider; 500 ms'i aşarsa iki tek tık olur.
- 250 ms çift tık alt sınırı ile en kısa gerçek aralık (281 ms) arasında pay dar.

## İpuçları
- Tık için kıstır-bırak yeter; uzun tutmak artık sürükleme yapmaz, ama 1.5 sn'yi geçme.
- Sürüklemek için kıstır ve eli belirgin şekilde (yarım avuçtan fazla) kaydır.
- Sağ tıkta yüzük ve serçe parmağı açık kalsın; işaret pozuna geçerken sağ tık iptal edilir.
