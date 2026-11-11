# Yumrukla pencere kontrolü

Sağ yumruk: ön plandaki uygun uygulama penceresini küçültür. Sol yumruk: uygulamanın
bu oturumda küçülttüğü son geçerli pencereyi geri açar. Bellek 32 hedefle sınırlıdır;
başarısız küçültme belleğe eklenmez. HWND ve PID her işlemden önce doğrulanır.

El önce 200 ms açık görünmeli; yumruk 350 ms tutulmalıdır. Tek tutuş bir komuttur.
Takip kaybı, bilinmeyen parmak, belirsiz kimlik, eski örnek, iki yumruk, duraklatma ve
acil durdurma aday hareketi iptal eder. Mod menüsü açıkken bu komutlar işlemez.
Küçültülecek hedef tutuş başında sabitlenir; ön plan değişirse küçültme yapılmaz.

Yönetici olarak ortak sözleşmeye yalnız `ActionKind.WINDOW_RESTORE` eklendi; normal
geri yükleme `ShowWindowAsync(SW_RESTORE)` ile aynı Windows sink yolundan gönderilir.
Dry-run'da gerçek işletim sistemi işlemi yoktur. Önizlemeye görünür Sürdür/Duraklat
düğmesi ve durum metni eklendi; UI bileşenlerinde yalnız yeni komutun Türkçe etiketi değişti.

Gerçek el/masaüstü kabulü: **bekliyor** (`windows_manual_tests.md`, W13).

Otomatik son doğrulama: **680 geçti, 3 manuel test seçilmedi** (`pytest -q`, offscreen).
Bu değişiklik için 18 yeni sahte veri testi eklendi; gerçek kamera/girdi/pencere işlemi yapılmadı.
