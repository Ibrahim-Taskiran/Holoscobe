# Tur 5: Anlık durum göstergesi

Ekranda küçük, tıklanamaz bir hap (StatusIndicator) durur. Her an tek durum görünür; renk + simge + metin birlikte verilir.
Öncelik yukarıdan aşağıya:

| Durum | Renk / simge | Anlamı |
|---|---|---|
| Duraklatıldı | sarı, `||` | Kontrol kapalı; el çırparak aç. |
| Takip yok (el görünmüyor) | kırmızı, `X` | Baskın el yok ya da kullanılamıyor. |
| Bekleyen eylem (ör. sürükleme) | mavi, `...` | Tıklama/sürükleme sürüyor; metin eylemin adıdır. |
| İmleç aktif | yeşil, `+` | İşaret pozu görüldü, imleç eli izliyor. |
| İmleç beklemede (işaret pozu yap) | gri, `o` | El açık ya da yumruk; imleç park halinde. |

- İptal nedeni: tıklama, sürükleme ya da sağ tık iptal olursa sebebi yaklaşık 1,5 sn kısa bir bildirimde görünür.
  Neden değişmediği sürece aynı metin tekrar gösterilmez.
- Aktif kalma yapışkandır: bir kez işaret etmek yeter; el belirgin açılana ya da yumruk olana kadar imleç izler.
- Ayarlardaki "Katman göster" kapalıysa gösterge de gizlenir.
- Gösterge yalnız durum değişince yeniden çizilir; arayüz işi izleme iş parçacığında yapılmaz (UiBridge sinyalleri).
