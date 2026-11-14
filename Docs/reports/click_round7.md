# Tıklama turu 7 — 2026-11-14

İşaretçi kipinde sağ el; imleç noktası temas başında sabitlenir.
| Hareket | Sonuç |
|---|---|
| Hareketsiz başparmak + işaret, 800 ms dolmadan bırak | Sol tık |
| İki hızlı işaret pinch | Aynı noktada iki tık; hızlı yeniden kurma korunur |
| Hareketsiz işaret pinch, 800 ms tut | Anında tek sağ tık; bırakma ve sonraki hareket eylem üretmez |
| Başparmak hem işaret hem orta uçta, 120 ms tut | Sol tuş basılır; el hareketi sürükler, kavramayı açmak bırakır |
| İşaret pinch sırasında 0,6 avuçtan fazla erken hareket | Alternatif sürükleme; artık uzun basma işlemez |
| Açık elden başparmak + orta | Önceki sağ tık korunur |
| Beş parmak tam bükük, önceden açık el, tut | Yumrukla pencere küçültme korunur; kavrama sayılmaz |

Yeni varsayılanlar: `right_long_press_ms=800`, `grab_confirm_ms=120`.
İkinci temas mevcut `pinch_decide_ms=60` penceresinde katılır; ayrı 250 ms pencere eklenmedi.
Kavrama eşikleri iki mesafede 0,33 / 0,48 avuç; açılma sektirmesi 70 ms.
Tek kare orta temas kaybı tuşu bırakmaz; doğrulama öncesi kayıp 120 ms sayacını yeniden başlatır.
`pinch_not_fist_*` korunur; tam bükülmüş işaret/orta kavrama başlatmaz.
Eksik el, kimlik değişimi ve belirsizlik hemen iptal; 150 ms eskilik ve 200 ms kayıp güvenliği korunur.
İptaller Türkçe `last_cancel` bırakır; başarılı tıklama/sürükleme başlangıcı temizler.

Eski kurala göre uyarlanan testler (silinen test yok):
- `test_ctrl_round6.py`: 800 ms altı sol tık; uzun tutma sağ tık; erken hareketle sürükleme.
- `test_ctrl_relative.py`, `test_integ_mouse.py`: sürükleme hareketi uzun basmadan önce; kısa tutma sınırı.
- `test_ctrl_pinch_mouse.py`: erken çift temas kavrama, geç temas önceki kararı değiştirmez.
- `test_ctrl_click_tuning.py`: çift temas örnekleri kavrama; uzun durağan kayıtlar sağ tık.
- `test_ctrl_sticky.py`: debounced işaret teması olan eşit mesafe kavrama olur.
- `tests/ui/test_pointer_settings.py`: eski yarım saniye sürükleme metni yeni hareketlerle değişti.
Yeni testler: 700 ms bırakma, 900 ms tek sağ tık, 40 ms sonra kavrama, temas sektirmesi,
iki mesafede histerezis, kayıp/kimlik/belirsizlik/eskilik/duraklatma, kavrama-yumruk ayrımı.
Entegrasyon: sentetik ham landmark zincirinde 10/30 fps kavrama ve uzun basma.

Doğrulanmadı: kavrama pozu gerçek kamerada hiç kaydedilmedi; sentetik test kamera kabulü değildir.
Sonraki yaklaşık 5 dk oturum: hareket, sol/çift tık, uzun basma, kavrayıp sürükleme, yumruk.
Takip bozulma nedenleri, kısa temas kaçakları, güven profili fps ve durağan kayma yeni kayıttan incelenmeli.
