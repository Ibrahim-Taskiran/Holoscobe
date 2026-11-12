# İmleç ve pinch tıklamaları (4. tur)

Bu belge `index_tap_controls.md` dosyasının yerini alır. Tüm tıklamalar yalnız **sağ el**
ve **İşaretçi** modunda çalışır. Baskın el ayarı bunu değiştirmez.

## İmleç: göreli mod ve debriyaj

İmleç varsayılan olarak **göreli** çalışır (dokunmatik yüzey gibi):

| Hareket | Sonuç |
|---|---|
| İşaret açık, diğer parmaklar kapalı | İmleç hareket eder. Hızlı hareket uzağa, yavaş hareket hassas gider |
| Eli aç (ya da kadrajdan çıkar) | İmleç yerinde kalır |
| Eli geri getir, yeniden işaret et | İmleç kaldığı yerden devam eder |

El ekranın tamamını taramak zorunda değildir; ikinci ekrana birkaç kısa hızlı hareketle
geçilir. Arada gerçek fareyle imleci taşıdıysan, yeniden işaret edince oradan devam eder.
**Ayarlar → İmleç Türü**: "Göreli (dokunmatik yüzey gibi)" ya da "Mutlak (kamera alanı = ekran)".
**İmleç Hızı** 0,5 ile 2,0 arasında, 0,1 adımla ayarlanır (varsayılan 1,0). Kalibrasyon
dikdörtgeni yalnız mutlak modda geçerlidir.

## Tıklamalar ve yumruk

| Hareket | Sonuç | Komut |
|---|---|---|
| Kısa başparmak + işaret pinch | Sol tık; imleç pinch sırasında durur | `LEFT_CLICK` |
| İki hızlı pinch (arada parmakları belirgin aç) | Çift tık (aynı konum) | `DOUBLE_CLICK` ya da aynı noktada iki `LEFT_CLICK` |
| Pinch'i yaklaşık yarım saniye tut, taşı, bırak | Sürükle bırak | `LEFT_DOWN` … `LEFT_UP` |
| Açık elden kısa başparmak + orta parmak pinch | Sağ tık | `RIGHT_CLICK` |
| Sağ yumruk tut (önce el açık olmalı) | Ön plandaki pencereyi küçült | — |
| Sol yumruk tut (önce el açık olmalı) | Son küçültülen pencereyi geri aç | — |

Pinch başlayınca imleç durur. Tık pinch başındaki konuma gönderilir; pinch sırasında
parmak oynasa da imleç kaymaz. Pinch eşikleri varsayılan 0,33 / 0,48 (avuç birimi).
İşaret parmağını kameraya doğru itme tıklaması varsayılan olarak kapalıdır. Kamera z
tahmini güvenilir değildi.

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
2. Mod İşaretçi olsun. İşaret açık, diğer parmaklar kapalı imleci gezdir. Eli aç, başka
   yere götür, yeniden işaret et: imleç yerinde kalmalı ve oradan devam etmeli.
3. Kısa pinch yap. Dry-run panelinde tek "Sol Tık" satırı görünmeli. Konum, pinch başındaki
   imleç konumu olmalı.
4. İki kısa pinch'i hızlıca yap. "Çift Tık" ya da aynı konumda iki "Sol Tık" görünmeli;
   ikinci tık imleç kaysa bile ilk tıkın konumuna gitmeli.
5. Pinch'i tut, eli taşı, bırak. Sırasıyla "Sol Tuş Basılı (Sürükle)", imleç hareketi ve
   "Sol Tuş Bırakıldı" görünmeli.
6. Açık elden başparmak ile orta parmağı kısa birleştir. "Sağ Tık" görünmeli.
7. Pinch tutarken eli kameradan çıkar. 200 ms içinde "Sol Tuş Bırakıldı" görünmeli.
8. Aynı adımları `--live` ile bir metin düzenleyicide tekrarla: seçim, sürükleme ve bağlam
   menüsü gerçekten çalışmalı.

Tepside **Hareket Rehberi** alt menüsü tüm hareketleri listeler.

Gerçek kamera ve masaüstü kabulü: **bekliyor**.
