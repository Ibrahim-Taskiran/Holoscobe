# Yönetici durumu: Holoscobe 1.0.0 (2026-11-18)

Özet: Yazılım tamam ve otomatik testlerden geçti. **Gerçek kamera ve gerçek ellerle donanım kabulü bekliyor.** Bu belgedeki hiçbir "geçti" donanım kanıtı değildir.

Otomatik test: **1455 geçti, 3 manuel seçilmedi, 0 başarısız** (`QT_QPA_PLATFORM=offscreen`, sahte donanım).
Komut: `$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest tests -q`.

Varsayılan dry-run. Gerçek komutlar yalnız `--live` ve başarılı acil durdurma kısayolu kaydından sonra çalışır. Kamera hatası Paused'a döner; kurtarma kendiliğinden etkinleştirmez.

## Özellik alanları

| Alan | Otomatik durum | Donanım kabulü |
|---|---|---|
| Kamera, takip, on parmak özellikleri | geçti (sahte veri) | bekliyor |
| Güvenlik: acil durdurma, eski örnek reddi, watchdog | geçti | bekliyor |
| İşaretçi: göreli imleç, debriyaj | geçti | bekliyor |
| Tıklama: sol, çift, sağ, sürükle bırak | geçti | bekliyor |
| Bekleyerek tıkla (`dwell.py`) | geçti | bekliyor |
| Kaydırma, yakınlaştırma, ses | geçti | bekliyor |
| Pencereler, yumruk küçült/geri aç, iki monitör | geçti | bekliyor |
| Komutlar modu ve uygulama profilleri (`swipe.py`) | geçti | bekliyor |
| Otomatik duraklatma | geçti | bekliyor |
| İlk açılış eğitimi | geçti (offscreen UI) | bekliyor |
| İmleç halkası, komut bildirimi, tık sesi | geçti (offscreen UI) | bekliyor |
| Sekmeli ayarlar, ön ayarlar, içe/dışa aktarma | geçti | bekliyor |
| Günlükleme, tanılama paketi, tek örnek koruması | geçti | bekliyor |
| Paketleme: build, self-test, release zip, install/uninstall | betikler yazıldı, CI tanımlı | bekliyor |
| Lisans | karar yok | sahip karar verecek |

Bilinen sınırlar: tek RGB kamera, yönetici yetkili uygulamalar kapsam dışı, exe imzasız (SmartScreen uyarısı olabilir).

## Elle test listesi (gerçek ellerle, sen yap)

Hazırlık: dahili kamera, dirsek masada, 40–70 cm, yüz önden aydınlık. Önce `--live` olmadan dene, sonra `--live`.

- [ ] **Eğitim:** Temiz ayarla ilk açılış. `%LOCALAPPDATA%\Holoscobe` altındaki ayar dosyasını yedekleyip sil. 8 adımı tamamla; Atla'yı da dene. Yeniden açınca eğitim çıkmamalı.
- [ ] **İmleç halkası:** Pinch'i ya da sabit imleci tut; halka dolmalı. Ayarlardan kapatınca görünmemeli.
- [ ] **Komutlar modu, PowerPoint:** Sunumu başlat. Sola kaydır = sonraki slayt, sağa = önceki. Kısa pinch = sonraki.
- [ ] **Komutlar modu, Chrome:** Sola = ileri, sağa = geri. Dönüş hareketi ters komut üretmemeli.
- [ ] **Komutlar modu, Spotify:** Sola = sonraki parça, sağa = önceki. Kısa pinch = oynat/duraklat.
- [ ] **Komutlar modu, diğer uygulama (ör. Not Defteri):** Sola/sağa = masaüstü değiştir. Yukarı = Görev görünümü, aşağı = Masaüstünü göster.
- [ ] **Komut bildirimi:** Her komutta doğru metin görünmeli. Tık sesini aç, duy.
- [ ] **Bekleyerek tıkla:** Ayarlardan aç. İmleci 1 sn sabit tut; sol tık gelmeli.
- [ ] **Otomatik duraklatma:** Süre seç, eli kadrajdan çıkar; kontrol duraklamalı.
- [ ] **Tanılama paketi:** Ayarlar > Gelişmiş > Tanılama raporu oluştur. Masaüstünde `Holoscobe-tanilama-*.zip` olmalı; içinde günlük olmalı, görüntü olmamalı.
- [ ] **İkinci örnek:** Çalışırken ikinci kez başlat. "Holoscobe zaten çalışıyor" demeli ve kapanmalı.
- [ ] **install.ps1:** `scripts\release.ps1` ile zip üret, aç, `install.ps1 -Desktop` çalıştır. Kısayoldan aç. `uninstall.ps1` sonrası klasör ve kısayollar gitmeli.
- [ ] **Eski kabul araçları:** `finger_test`, `stability_test`, `clap_test`, `profile_compare` (sonuçlar `Docs/reports/hw_*`).
- [ ] **Windows senaryoları:** `windows_manual_tests.md` içindeki bekleyen senaryolar (tarayıcı zoom, iki monitör, karma DPI, acil durdurma).

Bir madde başarısız olursa tanılama zip'ini ve ne yaptığını yaz.

## Sonraki karar

- Proje lisansı (sahip).
- Exe imzalama (ücretsiz yol yok; şimdilik SmartScreen notu yeterli).
