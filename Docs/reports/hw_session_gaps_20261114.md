# Holoscobe oturum analizi: kare aralığı ve boşluklar (2026-11-14)

Girdi: session_20261114-215223.csv, 7840 kare (salt okunur).

## 1. El sayısı ve kötü (BAD) kareler
| hands | kare | oran |
|---|---|---|
| 0 | 333 | 4.25% |
| 1 | 7413 | 94.55% |
| 2 | 94 | 1.20% |
- BAD kare: 722 (9.21%)
- El yok (dom_present=0): 567 (78.53% of BAD)
- Var ama kullanılamaz: 155 (21.47% of BAD)
  - dom_quality=degraded: 155

## 2. Kare aralığı (ms)
- Medyan 46.00, p95 63.00, max 94.00, >100 ms: 0 aralık
- Medyan (hands=1): 46.00 ms; medyan (hands=2): 46.00 ms

## 3. Boşluklar (İyi-kötü-iyi)
- Toplam boşluk: 51; <100: 13, 100-200: 11, 200-500: 18, >500: 9
- Boşlukta toplam süre: 18.28 s

## 4. Boşluklar >=200 ms (n=27), son İYİ kareye göre
- a. pinch_pu<0.48: 14
- b. kenar bölgesi (x<96/>544, y<72/>408): 4
- c. palm_scale<60: 2
- d. palm hareketi >25 px: 2
- e. finger_index != extended: 13
- Hiçbiri: 6
- İYİ karelerde medyan palm_scale: 83.00
- Boşluk öncesi son İYİ karede medyan palm_scale: 77.20

## 5. Boşluklar >=200 ms: kötü kare türü (çoğunluk)
- El yok çoğunlukta: 12; kullanılamaz çoğunlukta: 15; eşit: 0

## 6. Palm konumu (İYİ kareler)
- palm_x_px p5 163.28, p95 440.53
- palm_y_px p5 155.49, p95 377.21

## 7. hands=2
- Kare: 94; state=active oranı: 100.00%

Varsayımlar: aralık, sonraki karenin t_ms farkı (el sayısı o kareye göre); yüzdelik doğrusal interpolasyon; kovalar alt dahil, üst hariç (200-500 kovası 200 ve 500 dahil); boş değerli koşul sağlanmış sayılmaz; hareket iki son İYİ kare arası Öklid mesafesi; kenar boşlukları (başta/sonda BAD) gap sayılmaz; eksik değer sayısı (gap koşulları): 0.
