# Elle test listesi

Gerçek kamera ve ellerle, bir insan yapar. Otomatik testlerin geçmesi bunların yerine geçmez.
Aksi yazmayan her madde **bekliyor**.

Hazırlık: dahili kamera, dirsek masada, 40–70 cm, yüz önden aydınlık. Önce `--live` olmadan dene, sonra `--live`.
Bir madde başarısız olursa tanılama zip'ini ve ne yaptığını yaz.

## Genel

- [ ] **Açılış:** İmleç modu duraklatılmış başlar. Sürdür'e basınca etkinleşir, pencere küçülmez.
- [ ] **Mod değişimi:** Enstrüman ya da Çizim'den düğmeyle İmleç'e dönünce kontrol duraklar; önceden sen sürdürdüysen etkin kalır.
- [ ] **Eğitim:** Temiz ayarla ilk açılışta 8 adım. Atla'yı da dene. Yeniden açınca çıkmaz.
- [ ] **Ayarlar:** Bir şey değiştir, kaydet, kapat, aç: değer kalır.
- [ ] **Otomatik duraklatma:** Süre seç, eli kadrajdan çıkar; kontrol duraklar.
- [ ] **Tanılama paketi:** Masaüstünde `Holoscobe-tanilama-*.zip`; içinde günlük var, görüntü yok.
- [ ] **İkinci örnek:** "Holoscobe zaten çalışıyor" der ve kapanır.
- [ ] **Tek el hızlı yolu:** Tek el görünürken öbür eli hızla kaldırıp çırp; V çarkı gecikmeden açılır.

## İşaretçi

- [ ] İşaret açık, diğerleri kapalı: imleç gezer. Eli aç, başka yere götür, yeniden işaret et: kaldığı yerden devam eder.
- [ ] Kısa pinch: tek sol tık, pinch başındaki konumda. İki hızlı pinch: çift tık.
- [ ] Pinch'i 0,8 sn yerinde tut: tek sağ tık. Açık elden başparmak + orta: sağ tık.
- [ ] Üç parmak ucunu birleştir, taşı, aç: sürükle bırak. Pinch tutarken eli kadrajdan çıkar: 200 ms içinde sol tuş bırakılır.
- [ ] Bekleyerek tıkla açıkken imleci 1 sn sabit tut: sol tık.
- [ ] Sağ yumruk ön plandaki pencereyi küçültür, sol yumruk geri açar (önce el açık).

## Komutlar

- [ ] PowerPoint: sola = sonraki, sağa = önceki. Chrome: ileri / geri. Spotify: parça; kısa pinch = oynat/duraklat.
- [ ] Başka uygulama: masaüstü değişir; yukarı Görev görünümü, aşağı masaüstü. Dönüş hareketi ters komut üretmez.

## Enstrüman

- [ ] Ayarlar > Test sesi çal: temiz ses. Çalarken `Ctrl+Alt+Shift+F12`, `Win+L`, mod değişimi: ses anında kesilir.
- [ ] Serbest teller: uzun tel kalın, kısa tel ince. Çekerken nota telin üstünde yazar; bırakınca aynı nota kalır.
- [ ] Solo: 20 vuruşta 20 nota. Akor: 20 strumda doğru akor, kaçan tel yok.
- [ ] 5 dakika çalma: yanlış duraklatma ve yanlış çark açılışı yok.
- [ ] USB kulaklığı çıkar: bildirim çıkar, teller ekranda kalır, ses yeniden denenir.

## Çizim

- [ ] Fırça, taşıma ve yumruk arasında istenmeyen iz ya da silme yok. Renk çarkı doğru rengi seçer.
- [ ] X yap ve tut: sol üstteki yüzde 100'e çıkar, hepsi silinir. Loş ışıkta ve uzun kollu giysiyle de dene.
- [ ] Kalemle öbür kolun üstüne uzan: silinmez. El çırpma X ile karışmaz.

## Kedi

- [x] El ölçeği ve yönler doğru (2026-11-24).
- [ ] Elini yüzüne, yanağına, başının üstüne götür: pati önde kalır.
- [ ] Kollarını X yap: kedi de X yapar, patiler zıplamaz.
- [ ] Enstrümanda notalar, Çizim'de fırçanın patisi ve rengi doğru.

## Paket ve ölçüm araçları

- [ ] `scripts\release.ps1` zip'i, `install.ps1 -Desktop`, kısayoldan açılış, `uninstall.ps1`.
- [ ] `finger_test`, `stability_test`, `clap_test`, `profile_compare` (sonuçlar `Docs/reports/`, depoya girmez).
- [ ] Windows senaryoları W01–W17: [WINDOWS_TESTLERI.md](WINDOWS_TESTLERI.md).
