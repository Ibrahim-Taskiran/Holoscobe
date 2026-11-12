# Ölçüm araçları — 4. tur

2026-11-12. Yönetici Claude. Gerçek kamera/el/ikinci monitör doğrulaması **bekliyor**.

- Yeni dosyalar: `src/handcontrol/tools/click_record.py`, `pointer_probe.py`; `tests/tools/test_tools_click_record.py`, `test_tools_pointer_probe.py`; `scripts/click_record.ps1`, `pointer_probe.ps1`; bu rapor. Bağlama notları yalnız izin verilen `Docs/coordination/REQUESTS_codex.md` dosyasına eklendi. Controller/mapping/config/pipeline/common ve diğer mevcut kaynaklar değiştirilmedi.
- Test: `QT_QPA_PLATFORM=offscreen` ile `.venv\Scripts\python.exe -m pytest tests\tools -q`: **96 toplam / 96 geçen / 0 başarısız**, 8,28 s. Kamera, pencere ve gerçek fare kullanılmadı; gerçek donanım testi eklenmedi. İki PowerShell başlatıcısının `--help` kontrolü de çıkış 0 verdi. Paket kurulmadı, ağ/bulut/ücretli araç ve Git'e yazan komut kullanılmadı.
- Tıklama aracı `common.LiveSource` üzerinden kamera → takip → FeatureExtractor kullanır; Controller/Pipeline iç yapısını kullanmaz, OS girdisi göndermez. Varsayılan: 10 sn sabit, 10 sn gezdirme, 10 sol pinch, 10 sağ pinch, 5 sürükleme, 5 yumruk. Her tekrarda 1 sn açık referans, 4 sn hareket, 1 sn bırakma kaydı; sürükleme/yumruk yönergesinde 1 sn tutma vardır.
- CSV her benzersiz çıkarım karesini kaydeder: aşama/tekrar/bölüm/zaman, el kimliği/kalite, beş parmak, avuç/ölçek, 4–8 ve 4–12 piksel/avuç mesafeleri, işaret ucu/landmark 5, boyut/FPS. El yokken kare bilgileri korunur, el ölçümleri boş kalır. Ham görüntü/video kaydedilmez. JSON ve kısa Markdown tekrar ölçülerini, parmak dağılımlarını, titremeyi, kullanılan alanı ve FPS'yi içerir. Ctrl+C/kamera hatasında kısmi dosyalar korunur.
- Kapanma/açılma süreleri her tekrarın açık referansı ve minimumu arasındaki genliğin %35/%65 seviyelerinden **tahmin** edilir; kare zamanının ötesinde hassasiyet iddia edilmez. Kalite kaybı, kimlik değişimi, >250 ms boşluk, eksik bırakma veya bir yönergede birden çok kapanma olan tekrarlar eşik önermez. Aday kapama/açma aralıkları tüm tekrarların kapalı üst/açık alt mesafeleri arasında marj bırakır. Yumruk/diğer pinch mesafeleriyle çakışma ayrıca raporlanır: bu durumda mesafe tek başına güvenli ayrım sağlamaz, parmak durumu kapısı gerekir. Ayarlar otomatik değiştirilmez.
- Monitör sondası PMv2 DPI farkındalığıyla sınır/çalışma alanı/ölçek/birincil bilgisini listeler. Enter ve varsayılan 3 sn sonrası her monitörde merkez + dört köşenin 20 px içine `WindowsInput.move_pointer` gönderir. `GetCursorPos` ile dx/dy ve Öklid sapmasını ölçer. Varsayılan 2 px toleransta beş noktanın tamamı başarılıysa “ulaşıldı” der. Reddetme/hata/kesinti sırasında da başlangıca dönüş denenir ve gerçek konumla doğrulanır; Windows dönüşü reddederse rapor bunu başarısız gösterir. Tıklama gönderilmez.

Kullanıcının çalıştıracağı komutlar (herhangi bir klasörden):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ibrah\Documents\GitHub\Project\Holoscobe\scripts\click_record.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ibrah\Documents\GitHub\Project\Holoscobe\scripts\pointer_probe.ps1"
```

Önce Holoscobe'u kapatın veya kamera/canlı kontrolünü durdurun. Kayıtta yalnız sağ eli gösterin; yönerge gelmeden pinch yapmayın. Sağ el etiketi ters görünüyorsa `click_record.ps1 --swap-handedness` kullanın. Alternatif kamera: `--camera-index 1 --backend dshow`. Süre/tekrar seçenekleri: `--still-seconds`, `--range-seconds`, `--pinch-repeats`, `--drag-repeats`, `--fist-repeats`, `--trial-seconds`, `--open-seconds`, `--hold-seconds`. İki başlatıcı da argümanları geçirir, `PYTHONPATH=src` ve `PYTHONUTF8=1` ayarlar.

Çıktılar: `Docs/reports/hw_click_<tarih-saat>.csv`, `.json`, `.md`; `Docs/reports/hw_pointer_probe_<tarih-saat>.md`. `--out-dir` ile başka yerel klasör seçilebilir. Dosya adlarında çakışmayı önlemek için mikrosaniye de vardır.

Kalan işler: kullanıcı gerçek kayıtları üretmeli; Claude H bunlarla eşik/parmak durumu kapısını ve göreli imleç eşlemesini ayarlamalı. Monitör sondası başarılı, el ile ikinci ekran geçişi başarısızsa Windows erişimi ile el eşlemesi ayrı değerlendirilmelidir. Temsilî el/ışık/mesafe koşullarında aday eşikler bağımsız tekrar kaydıyla doğrulanmalı. Sahte test sonuçları donanım başarısı sayılmaz.
