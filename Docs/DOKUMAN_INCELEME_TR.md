# Doküman incelemesi ve alınan kararlar

Tarih: 12 Kasım 2026

[Teknik şartname](Windows_Hand_Gesture_Control_Spec.md) yerinde v1.1 olarak güncellendi. [Yol haritası](ROADMAP_TR.md) bu kararları uygulama sırasına dönüştürür. Mevcut İngilizce şartname dili korundu; açıklama ve plan Türkçe hazırlandı.

## Bulunan eksikler ve çözümler

| Konu | Önceki eksik veya çelişki | Uygulanan düzeltme |
|---|---|---|
| Tüm parmaklar | “Parmakları takip et” ifadesi vardı, parmak başına çıktı ve kalite ölçütü yoktu. | On parmağın adı, açık/bükülü/belirsiz durumu, başparmağa özel geometri ve 400 sunumluk kabul testi eklendi. |
| Güvenilirlik | Tam örtüşmede modelin tahminiyle gerçek gözlem ayrılmıyordu. | Tek kamera sınırı açıklandı; belirsizlik, geometri ve zaman kontrolleri eklendi. Gizli parmaklar için kusursuzluk iddiası kaldırıldı. |
| Ücretsiz kullanım | Yerel çalışma vardı; ücretsiz araç, model ve dağıtım zorunluluğu açık değildi. | Ek yazılım/hizmet bedeli ve zorunlu yeni donanım yasaklandı; model/bağımlılık lisans denetimi eklendi. Mevcut Windows ve donanım önkoşulu açıklandı. |
| Lisans | MediaPipe kod lisansı ile model lisansı birbirinden ayrılmamıştı. | İndirilen modelin kendi dağıtım kanıtı ve hash manifesti zorunlu oldu; bilinmeyen lisans “uygun” sayılmıyor. |
| Güven puanı | “Handedness and score” doğruluk puanı gibi yorumlanabilirdi. | Sağ/sol sınıflama puanı ile nokta doğruluğu ayrıldı; API'nin sunmadığı parmak güveni uydurulmuyor. |
| Kamera profili | Başlangıç çözünürlüğü vardı, kalite karşılaştırması yoktu. | 480p/720p destek durumuna göre aynı pozlarda kıyaslanıyor; seçim doğruluk ve gecikme birlikte geçerse yapılıyor. |
| Acil durdurma | Geliştirme listesinde gerçek kontrollerden sonra geliyordu. | İlk OS komutundan önce tepsi, kısayol, bağımsız zaman aşımı ve iptal mekanizması zorunlu oldu. |
| Kamera kapalıyken etkinleştirme | Kamera kapalıyken clap/Resume davranışı belirsizdi. | Kamera yaşam döngüsü ayrıldı; kamerayı açma Paused'a döndürüyor, kendiliğinden etkinleşmiyor. |
| Jest çakışması | El çırpma, açık avuç menüsü ve çift pinch arasında kesin giriş kuralları yoktu. | Öncelik, açık parmak koşulu, menü durağanlığı, pinch başlangıç penceresi ve nötr bekleme tanımlandı. |
| Menü ve pencere sürükleme | Windows menüsünün nasıl açılacağı; aynı pinch'in sürükleme mi seçim mi olduğu belirsizdi. | Kısa pinch menü açıyor, 250 ms tutuş sürüklüyor. Menü kendi imlecini kullanıyor; kapatma yeni ve ayrı tutuş gerektiriyor. |
| Zoom/kaydırma hedefi | Geçerli pencere ile gerçekten tekerlek alan pencere farklı olabilirdi. | Odak ve işaretçi hedefi doğrulaması, hedef değişince iptal ve açık kullanıcı odaklaması tanımlandı. |
| Kare eskimesi | Yalnızca kayıp el zaman aşımı, kilitlenen çıkarım döngüsünde yetersizdi. | 150 ms eski örnek reddi ve döngüden bağımsız 200 ms iptal gözcüsü eklendi. |
| Maskot | GLB desteğinin ücretsiz renderer ve lisans gereksinimi net değildi. | Çekirdek sonrasına alındı; önce prosedürel karakter, sonra ayrı renderer/varlık denetimi. |
| Kabul kararı | Test hedefi tutmazsa yalnızca raporlama/tuning deniyordu. | Zorunlu eşikler geçmeden v1 kabul edilmiyor; gerçek donanım ile sahte test sonuçları ayrılıyor. |

## Korunan doğru kararlar

Yerel MediaPipe Tasks mimarisi; kamera ile arayüz işlerini ayırma; en yeni kareyi işleme; metrik olmayan iki-el derinliğini kullanmama; DPI ve negatif ekran koordinatlarına dikkat etme; HWND/süreç kimliğini doğrulama; pencereyi normal kapatma isteğiyle kapatma; yönetici yetkisi gerektirmeme ve normal çalışmada görüntü kaydetmeme kararları korundu.

## Kaynaklarla doğrulanan temel noktalar

Hand Landmarker her el için 21 nokta ile el tarafı ve koordinat çıktıları sağlar. Bu özellik, on parmağı temsil etmek için uygun bir başlangıçtır; hedef kameradaki doğruluk ayrıca ölçülmelidir. [Resmî Hand Landmarker rehberi](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python)

Sonuç API'si handedness, hand_landmarks ve hand_world_landmarks alanlarını tanımlar; sağ/sol sınıflama skorunu her parmağın doğruluk ölçümü saymak doğru değildir. [Resmî sonuç API'si](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/HandLandmarkerResult)

Qt for Python açık kaynak lisans seçenekleri sunar; bazı Qt modüllerinin koşulları farklıdır. Bu nedenle ücretsiz dağıtım kullanılan modüllerin ve paket içeriğinin denetlenmesiyle planlandı. [Qt for Python](https://doc.qt.io/qtforpython-6/) · [Qt lisans ve modül bilgileri](https://doc.qt.io/qt-6/licensing.html)

MediaPipe deposunun lisansı model dosyasının dağıtımına ilişkin kanıt yerine kullanılmayacak; indirilen model ayrıca incelenecek. [MediaPipe depo lisansı](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE)

## Uygulama sırasında doğrulanacaklar

- Hedef laptopta gerçek FPS, parmak doğruluğu, titreme ve gecikme henüz ölçülmedi.
- Python ve paketlerin kesin sürüm kombinasyonu henüz kurulup sınanmadı.
- Kullanılacak model artifact'ının kesin sürümü, hash'i ve dağıtım kanıtı henüz seçilmedi; Aşama 0'ın zorunlu işi.
- Maskotun gelecekteki 3D renderer'ı ve GLB varlığı seçilmedi.
- Projenin kendi kaynak lisansı kamuya dağıtımdan önce netleştirilecek; bu incelemede lisans atanmadı.

%95 doğruluk gibi değerler proje için önerilen kabul eşikleridir; araştırma kaynağından alınmış başarı garantisi veya yapılmış test sonucu değildir. Donanım bunları karşılamıyorsa sonuç açıkça raporlanacak, ücretli çözüme geçilmeyecek.
