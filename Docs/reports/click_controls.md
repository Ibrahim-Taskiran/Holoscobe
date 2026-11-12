# Pinch ile fare tıklamaları (3. tur)

Bu belge `index_tap_controls.md` dosyasının yerini alır. Tüm tıklamalar yalnız **sağ el**
ve **İşaretçi** modunda çalışır. Baskın el ayarı bunu değiştirmez. Sağ işaret parmağı imleci
taşımaya devam eder. Sağ yumrukla küçültme ve sol yumrukla geri açma değişmedi.

## Hareketler

| Hareket | Sonuç | Komut |
|---|---|---|
| Başparmak + işaret kısa pinch | Sol tık | `LEFT_CLICK` |
| Kısa pinch, ikincisi yaklaşık 500 ms içinde başlar | Çift tık (aynı konum) | `DOUBLE_CLICK` ya da aynı noktada iki `LEFT_CLICK` |
| Pinch'i yaklaşık 350 ms tut (ya da pinch'le eli belirgin taşı), taşı, bırak | Sürükle bırak | `LEFT_DOWN` … `LEFT_UP` |
| İşaret ve yüzük/serçe açıkken başparmak + orta parmak kısa pinch | Sağ tık | `RIGHT_CLICK` |

Pinch başlayınca imleç o anki yerde sabitlenir. Tık bu konuma gönderilir; pinch sırasında
parmak oynasa da imleç kaymaz. İşaret parmağını kameraya doğru itme tıklaması varsayılan
olarak kapalıdır. Kamera z tahmini güvenilir değildi.

## İptal kuralları

- Pinch tutulursa ya da el belirgin kayarsa tık üretilmez; onun yerine sürükleme başlar.
- Başparmak ile orta parmak zaten birleşikken görünen el sağ tık üretmez; önce parmakları aç.
- Sürükleme sırasında pinch bırakılınca sol tuş bırakılır (`LEFT_UP`).
- Takip kaybı, eski kamera örneği, duraklatma, mod/menü değişimi ve acil durdurma
  açık hareketi iptal eder. Basılı sol tuş en geç 200 ms içinde bırakılır.
- Sol el pinch'i imleç ya da tık üretmez.
- Dry-run Windows'a komut göndermez; yalnız komut metnini gösterir (ör. "Çift Tık").

## Gerçek kamerayla elle kontrol

1. `python -m handcontrol.app` ile dry-run başlat. Tepsiden **Sürdür** seç ya da el çırp.
2. Mod İşaretçi olsun. Sağ işaret parmağıyla imleci gezdir.
3. Kısa pinch yap. Dry-run panelinde tek "Sol Tık" satırı görünmeli. Konum, pinch başındaki
   imleç konumu olmalı.
4. İki kısa pinch'i hızlıca yap. "Çift Tık" ya da aynı konumda iki "Sol Tık" görünmeli;
   ikinci tık imleç kaysa bile ilk tıkın konumuna gitmeli.
5. Pinch'i tut, eli taşı, bırak. Sırasıyla "Sol Tuş Basılı (Sürükle)", imleç hareketi ve
   "Sol Tuş Bırakıldı" görünmeli.
6. İşaret ve yüzük/serçe parmak açıkken başparmak ile orta parmağı kısa birleştir. "Sağ Tık" görünmeli.
7. Pinch tutarken eli kameradan çıkar. 200 ms içinde "Sol Tuş Bırakıldı" görünmeli.
8. Aynı adımları `--live` ile bir metin düzenleyicide tekrarla: seçim, sürükleme ve bağlam
   menüsü gerçekten çalışmalı.

Tepside **Hareket Rehberi** alt menüsü tüm hareketleri listeler.

Gerçek kamera ve masaüstü kabulü: **bekliyor**.
