# Windows click actions — 3. tur

2026-11-12. Yönetici: Claude.

- Değişen dosyalar: `src/handcontrol/windows/input.py`, `src/handcontrol/windows/sink.py`, `tests/windows/test_input.py`, `tests/windows/test_sink.py`, `Docs/reports/windows_manual_tests.md`, bu rapor. İzin verilen sözleşme istisnasıyla `src/handcontrol/contracts.py` içindeki `ActionKind`'a yalnız dört üye eklendi.
- Sağ tık, beklemesiz çift tık, sol basılı tutma/bırakma ve doğru sol/sağ UP yönlendirmesi tamamlandı. Basılı sol tuş sırasında yeniden basma ve sol tıklama reddedilir; doğrudan input adapter'da mevcut tutuş korunur, imleç hareketi kullanılabilir.
- Epoch ve 150 ms sınırı korundu. Reddedilen veya koordinatı eksik `LEFT_UP`, imleci taşımadan `release_all()` çağırır. Taşıma hatasında da bırakma denenir. Sink'te başarısız pointer eylemi ve exception temizliği, epoch değişimi ve kapanış test edildi. Windows UP olayını reddederse defter kaydı korunur; sonraki temizlik yeniden dener, işletim sistemi reddi altında fiziksel bırakma garanti edilemez.
- Ek küçük düzeltme: saat/yaş hesabı exception korumasına alındı; saat hatası da basılı tuşları temizler. Windows katmanındaki TODO/FIXME/NotImplemented taramasında ek yarım iş bulunmadı (`HotkeyConflictError` içindeki `pass`, boş exception sınıfıdır).
- Test: `QT_QPA_PLATFORM=offscreen` ile `.venv\Scripts\python.exe -m pytest tests\windows -q`. Son sonuç: **toplam 184 / geçen 184 / başarısız 0**, 0.40 s. Tüm olaylar sahte API ile doğrulandı; gerçek SendInput çağrılmadı. Bytecode kapatıldı, pytest geçici/cache yolları `tests/windows` altında tutuldu. `git diff --check` hata vermedi.
- Kalan işler: W14 sağ tık, W15 çift tık, W16 sürükle-bırak, W17 takılı tuş kurtarma dahil 17 donanım senaryosu **bekliyor**. Jest/denetleyici ve UI entegrasyonu Claude tarafında; tam test takımını yönetici çalıştırmalı.
- Çakışma riski: ortak tek kod dosyası `contracts.py`; dört üye artık mevcut, tekrar eklenmemeli. Claude tarafının eşzamanlı `app.py`, `dryrun.py`, `ui/**` ve sahiplik değişikliklerine dokunulmadı. Git'e yazan komut çalıştırılmadı; paket kurulmadı.
