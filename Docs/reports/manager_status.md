# Yönetici teslim durumu — 2026-11-12

Pipeline tamamlandı; `python -m handcontrol.app` girişi kamera/takip, pipeline, Qt köprüsü,
tepsi, önizleme, ayarlar, kalibrasyon ve katmanları bağlıyor. Dry-run varsayılan; gerçek sink
yalnız `--live` ve başarılı global kısayol kaydından sonra oluşturulur. Bağımsız watchdog,
epoch eşleme, oturum/askıya alma/ekran değişimi iptali ve sıralı kapanış bağlıdır.
Kamera hatası Paused'a döner; kurtarma kendiliğinden etkinleştirmez.

| Yol haritası | Yazılım/sahte veri doğrulaması | Gerçek kabul kapısı |
|---|---|---|
| Aşama 0 — Teknik temel | geçti: mevcut bağımlılıklar, yerel zincir | bekliyor: bu teslimde donanım yeniden ölçülmedi |
| Aşama 1 — Kamera/on parmak | geçti: kamera, takip, özellik testleri | bekliyor: 400 sunum, beş dakika iki el, handedness |
| Aşama 2 — Güvenlik/komutsuz jest | geçti: pipeline, watchdog, epoch, dry-run | bekliyor: gerçek clap, acil durdurma ve zaman sınırları |
| Aşama 3 — İmleç/tıklama | geçti: eşleme/filtre/eylem testleri | bekliyor: gerçek imleç doğruluğu ve tıklama |
| Aşama 4 — Kaydırma/zoom/ses | geçti: denetleyici ve sahte bağdaştırıcılar | bekliyor: tarayıcı zoom, aygıt değişimi, fiziksel tuşlar |
| Aşama 5 — Pencere/iki monitör | geçti: hedef kimliği ve yerleşim testleri | bekliyor: iki yön, karma DPI, boşluklar, takılan hedef |
| Aşama 6 — Sağlamlaştırma/dağıtım | bekliyor: paketleme, uzun süreli kullanım, çevrimdışı dağıtım kabulü | bekliyor |
| Aşama 7 — İsteğe bağlı maskot | bekliyor: ürün kapsamı ve animasyon | bekliyor |

Başarısız otomatik test: **0**. Tam takım: **665 toplanan, 662 geçen, 3 manuel seçilmeyen**;
`QT_QPA_PLATFORM=offscreen`, pytest geçici/önbellek dizinleri `tests/.tmp_full_manager` ve
`tests/.cache_manager`. Komut: `.venv\Scripts\python.exe -m pytest -q`.
İlk kapsam çalıştırması sandbox geçici dizin erişimi nedeniyle hata verdi; aynı kapsam izinli
ortamda 644/644, UI 10/10 geçti. Yeni uygulama testleri 8/8 geçti. Eşikler/test beklentileri
zayıflatılmadı. Gerçek kamera açılmadı, pencere gösterilmedi ve OS girdisi gönderilmedi.

İlk commit: `f454a82 feat(pipeline): complete headless gesture controller integration`.
İkinci teslim commit'i app, uygulama testleri, kamera-hatası Paused politikası, menü seçim
alanı/imleç örtüşmesi için küçük UI düzeltmesi ve bu belgeleri içerir.

Elle yapılacaklar: README'deki dry-run komutuyla başlatıp tepsi, ayarlar, kalibrasyon ve
kamera yaşam döngüsünü kontrol edin. Ardından `finger_test`, `stability_test`, `clap_test`,
`profile_compare` araçlarını çalıştırın; raporları `Docs/reports/hw_*` altında saklayın.
Windows canlı kabul adımları `windows_manual_tests.md` içindeki 12 bekleyen senaryodur.
Canlı çalıştırma: `.venv\Scripts\python.exe -m handcontrol.app --live` (önce PYTHONPATH=src).
Varsayılan F12 kaydı OS/debugger nedeniyle reddedilebilir; dry-run ayarlarından serbest
bir kombinasyon atayın ve live'ı yeniden başlatın.

Sınırlar: donanım kabulü tamamlanmadı; UI'deki smoothing/detection/tracking eşiği ve
Windows başlangıç/isteğe bağlı maskot seçenekleri bu bağlamada yeni işletim sistemi
özelliğine dönüştürülmedi. Kalıcı config sözleşmesindeki alanlar kaydedilir ve pipeline'a
uygulanır. `.claude/` ve `CLAUDE.md` kullanıcıya ait mevcut untracked dosyalar olarak bırakıldı.
Paket kurulmadı, ücretli araç/API/bulut servisi kullanılmadı.
