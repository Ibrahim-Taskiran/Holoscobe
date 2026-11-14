# Oturum telemetrisi

Gerçek kullanımda imlecin neden durduğunu ya da tıklamanın neden olmadığını görmek için.

## Kayıt
1. `python -m handcontrol.app --telemetry` (canlı için `--live` ekleyin). Varsayılan kapalıdır.
2. Dosya: `%LOCALAPPDATA%\Holoscobe\telemetry\session_<YYYYMMDD-HHMMSS>.csv`. Yol açılışta yazdırılır.
3. Uygulamayı kapatınca dosya tamamlanır (yaklaşık saniyede bir diske yazılır).

## Rapor
`python -m handcontrol.tools.session_report <csv> [--out <md>]`
Varsayılan çıktı: `Docs/reports/hw_session_<damga>.md`. Eksik sütun için "veri yok" yazılır.

## Ne saklanır
Yalnız sayılar ve kısa metinler. Görüntü, landmark noktaları ya da ses yoktur. Dosya sadece bu bilgisayardadır.

## Sütunlar
- `t_ms`, `age_ms` (yakalama-işleme gecikmesi), `hands`, `dom_present`, `dom_quality`
- `finger_thumb`, `finger_index`, `finger_middle`, `finger_ring`, `finger_little`
- `pinch_pu` (başparmak-işaret mesafesi, avuç birimi), `palm_x_px`, `palm_y_px`, `palm_scale_px`
- `events` (kare olayları, `|` ile), `actions` (gönderilen eylemler, `|` ile; imleç hareketi hariç), `moves` (imleç hareketi sayısı)
- `state`, `mode`, `pending_action`, `notice`, `pointer_x`, `pointer_y`, `dropped_actions`
- `pointer_engaged`, `tracking_ok`, `last_cancel` (denetleyicide henüz yoksa 0 / 1 / boş yazılır)
- `dom_reasons` (baskın elin kalite düşme nedenleri + kare nedenleri, `|` ile; ör. `palm_small`, `palm_edge_on`, `bone_ratio`, `discontinuity_speed|scale|hold`, `slow_processing`, `identity_ambiguous`, `ambiguity_hold`, `overlap`, `same_handedness`, `merge`, `too_many_hands`, `hand_unlocatable`, `palm_tiny`, `landmarks_nonfinite`)
- `mid_pinch_pu` (başparmak-orta parmak ucu mesafesi, avuç birimi; el yoksa boş)

## Rapor tanımları
- Pinch denemesi: mesafe 0.33 altına inip 0.48 üstüne çıkar.
- Poz titremesi: bağlantı 500 ms'den kısa kopup el yerindeyken geri gelir.
- Takip bozulma nedenleri: kullanılabilir olmayan karelerde neden sayıları; 200 ms+ kopukluğun ilk karesinin nedenleri.
- Pinch süre tablosu: <200 / 200-480 / 480-1000 / >1000 ms denemeler ve sonucu (sol tık, sürükleme, sağ tık, iptal, hiçbiri).
- Ortalama fps = kare sayısı / süre; ayrıca medyan kare aralığı.
- İmleç durması: bağlıyken el >= 0.25 avuç boyu oynar, imleç >= 200 ms kıpırdamaz.
