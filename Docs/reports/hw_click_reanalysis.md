# Hw click yeniden analiz

Girdi: `Docs/reports/hw_click_20261112-152708-382361.csv` (5914 satır)

## 1. Statü sayıları
| Faz | Satır | ok | degraded | ambiguous | missing | ok % |
|---|---|---|---|---|---|---|
| still | 295 | 295 | 0 | 0 | 0 | 100.00 |
| range | 293 | 274 | 0 | 19 | 0 | 93.52 |
| left_pinch | 1773 | 1628 | 112 | 33 | 0 | 91.82 |
| right_pinch | 1777 | 1673 | 39 | 23 | 42 | 94.15 |
| drag | 888 | 668 | 159 | 5 | 56 | 75.23 |
| fist | 888 | 865 | 23 | 0 | 0 | 97.41 |

## 2. Jitter, poz, boşluklar, ölçek
| Faz | Jitter medyan px | Jitter p95 px | İşaret % | Açık el % | Boşluk <100 | 100-200 | 200-500 | >500 | Palm scale medyan px |
|---|---|---|---|---|---|---|---|---|---|
| still | 0.69 | 2.76 | 100.00 | 0.00 | 0 | 0 | 0 | 0 | 82.24 |
| range | 11.43 | 19.52 | 99.27 | 0.00 | 0 | 0 | 0 | 1 | 78.93 |
| left_pinch | 0.42 | 3.85 | 0.00 | 48.65 | 3 | 1 | 2 | 2 | 73.90 |
| right_pinch | 0.54 | 7.05 | 0.72 | 34.43 | 1 | 3 | 1 | 4 | 78.19 |
| drag | 3.07 | 11.48 | 0.00 | 34.73 | 1 | 0 | 2 | 6 | 93.67 |
| fist | 0.52 | 3.07 | 0.69 | 27.86 | 9 | 5 | 0 | 0 | 77.60 |

## 3. Parmak 'unknown' oranı (ok satırları, %)
| Faz | thumb | index | middle | ring | little |
|---|---|---|---|---|---|
| still | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| range | 11.68 | 0.73 | 0.73 | 0.73 | 0.73 |
| left_pinch | 0.61 | 0.86 | 0.86 | 0.86 | 0.86 |
| right_pinch | 0.60 | 2.03 | 1.02 | 1.26 | 0.42 |
| drag | 0.60 | 0.90 | 0.60 | 0.60 | 0.60 |
| fist | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

## 4. Sabit ve hareket fazları
- `still` sürüklenme (max-min): palm_x = 42.74 px, palm_y = 107.78 px
- `still` detrend titreme: RMS = 0.90 px, p95 = 2.17 px
- `still` poz titremesi (<300 ms): sayı = 0, medyan süre = veri yok ms
- `range` poz titremesi (<300 ms): sayı = 1, medyan süre = 78.00 ms

Varsayımlar: fazlar dosya sırasında ayrı ele alındı; yüzdelikler doğrusal interpolasyon; boşluk kovaları 100 ve 200 ms alt sınırları dahil, 500 ms dahil (200-500); poz titremesi süresi = ilk işaretsiz satır ile sonraki ilk işaretli satır arasındaki fark.
