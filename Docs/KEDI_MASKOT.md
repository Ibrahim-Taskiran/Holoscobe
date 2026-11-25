# 3B kedi maskot

Kamera açıkken bütün modlarda ekranın sağ alt köşesinde duran, kullanıcıyı ayna gibi taklit eden kedi.
Kullanım: [README](../README.md#3b-kedi-maskot).

Durum (2026-11-26): el ölçeği ve yönler gerçek kamerada onaylandı. Çapraz kol, yüz önü, notalar ve fırça onay bekliyor.

## Veri akışı

```
kamera karesi -> Perception (ayrı iş parçacığı: yüz 15 Hz, gövde 8 Hz) -> FaceInfo / BodyInfo
el özellikleri (izleme iş parçacığı) -> HandInfo
                      Retargeter.pose() -> MascotPose -> PoseSmoother (yay) -> CatRig.solve() -> kemik matrisleri
                      CatRenderer (ekran dışı OpenGL 3.3, PBO) -> QImage -> MascotWindow
```

Kedi gizliyken yüz ve gövde takibi tamamen durur.

| Dosya | Görev |
|---|---|
| `mascot/perception.py` | MediaPipe yüz ve poz modelleri |
| `mascot/retarget.py` | Ölçümleri poza çevirir, hangi patinin hangi eli taklit ettiğini seçer |
| `mascot/rig.py` | 12 kemik, kol çözümü, çarpışma |
| `mascot/renderer.py` | Tüy geometrisi, gözler, fırça |
| `mascot/notes.py` | Enstrüman modundaki notalar |
| `mascot/window.py` | Şeffaf, tıklama geçiren pencere |

## Eller ve patiler

- Sağ el ekranın sağındaki patidir. İki el, hareketin sürekliliği ve sol/sağ etiketi birlikte değerlendirilerek atanır;
  eller çaprazlanınca patiler yer değiştirmez.
- Öbür elin yanında kaybolan el 1,5 saniye yerinde tutulur.
- Birbirine değen ya da çapraz kollarda poz modelinin bilekleri düşük görünürlükle de kullanılır.

## Çarpışma ve X

- Kaldırılan pati, kafa ve gövde için ölçülmüş iki elipsoidin önünde kalır.
- Yüzün önüne yetişmek için kol en çok %18 uzar, omuz en çok 0,28 birim kayar. Yine yetişmezse pati aşağı iner.
- Yan yana iki pati arasında boşluk bırakılır. Bilekler yer değiştirince kollar kesişir ve sağ kol öne geçer;
  kısa kollarla X belli olsun diye çaprazlık abartılır.
- Ölçüm: 1320 pozda patinin kafaya gömüldüğü poz 284'ten 1'e indi. Ön kolun dirseğe yakın kısmı bazı yüksek pozlarda
  yanağın arkasına hafifçe girer; önden görünmez.

## Modlara göre

- **Enstrüman (etkin):** kedinin arkasından notalar yükselir; tele her vuruş ek nota çıkarır.
- **Çizim:** kalem çizerken ya da renk çarkı açıkken sağ eli taklit eden patide seçili renkte fırça. Çizgi bitince 1,2 sn kalır.

## Modeli yeniden üretme

Blender 5.1 gerekir (uygulamayı çalıştırmak için gerekmez):

```
blender -b --python scripts/cat_model.py --python scripts/build_mascot.py
```

`scripts/cat_model.py` modeli kurar, `scripts/build_mascot.py` onu `assets/mascot/cat.npz` dosyasına aktarır. Kollar ayrı
mesh'tir ve yarı açık pozda üretilir; böylece dirsek ve bilekte boğum oluşmaz.
