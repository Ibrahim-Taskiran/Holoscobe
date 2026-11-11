# Holoscobe

Kamerayla el hareketi kullanarak Windows 11 masaüstünü kontrol eden uygulama. İki elin on parmağını ayrı takip eder, iki monitörü destekler, kurulumdan sonra internetsiz çalışır ve ücretli hiçbir araç ya da servis gerektirmez.

> **Durum: geliştirme aşamasında.** Kodun büyük kısmı yazıldı ve birim testleri geçiyor, ancak bu testler sahte veriyle çalışır. Gerçek kamera, gerçek el ve iki monitör doğrulamaları henüz yapılmadı. Gerçek Windows komutları bu doğrulamalar geçene kadar kapalıdır.

## Ne yapar

| Mod | Hareket | Sonuç |
|---|---|---|
| Hepsi | İki elle bir kez el çırpma | Kontrolü açar ya da duraklatır |
| İşaretçi | Baskın elin işaret parmağı | İmleci hareket ettirir |
| İşaretçi | Kısa başparmak–işaret pinch | Sol tık |
| Kaydırma | Pinch + dikey hareket | Dikey kaydırma |
| Yakınlaştırma | İki elle pinch, elleri aç/kapat | Ctrl + tekerlek |
| Ses | Pinch + dikey hareket | Sistem sesi |
| Pencereler | Pinch'i 250 ms tut | Pencereyi sürükler |
| Pencereler | Kısa pinch | Küçült, büyüt, diğer monitöre taşı, kapat menüsü |

Mod değiştirmek için baskın olmayan elin açık avucunu 600 ms sabit tut.

## Güvenlik

- Uygulama duraklatılmış başlar.
- Acil durdurma kısayolu: `Ctrl+Alt+Shift+F12`.
- 150 ms'den eski kamera örneği komuta dönüşmez.
- Takip kaybolursa uygulamanın bastığı tüm girişler en geç 200 ms içinde bırakılır.
- Pencere kapatma yalnız normal kapatma isteğiyle yapılır; süreç sonlandırılmaz, kaydedilmemiş belge uyarısı korunur.
- Normal çalışmada görüntü kaydedilmez. Kareler yalnız bilgisayarda işlenir.

## Gereksinimler

- Windows 11 x64
- Web kamerası (HP Victus dahili kamerasıyla geliştiriliyor)
- Python 3.11
- [uv](https://docs.astral.sh/uv/) (kurulum betiği kullanır)

## Kurulum

```powershell
.\scripts\setup.ps1
```

Betik sanal ortamı kurar, sabitlenmiş paketleri yükler, el modelini indirir ve SHA-256 değerini `assets/model_manifest.json` ile karşılaştırır. Model dosyası depoya dahil değildir.

## Testler

```powershell
.\scripts\run_tests.ps1
```

Fareyi oynatan, sesi değiştiren ya da pencere açan testler `manual` olarak işaretlidir ve varsayılan olarak atlanır.

### Gerçek kamera kabul testleri

Bunları bir insan, gerçek elleriyle çalıştırır. Sonuçlar `Docs/reports/hw_*` altına yazılır.

```powershell
.venv\Scripts\python.exe -m handcontrol.tools.finger_test      # on parmak, 400 sunum
.venv\Scripts\python.exe -m handcontrol.tools.stability_test   # 5 dakika iki el
.venv\Scripts\python.exe -m handcontrol.tools.clap_test        # el çırpma
.venv\Scripts\python.exe -m handcontrol.tools.profile_compare  # 480p ve 720p karşılaştırma
```

## Yapı

```
src/handcontrol/
  contracts.py     Modüller arası ortak tipler
  camera.py        Kamera yaşam döngüsü, en yeni kare tamponu
  tracking.py      MediaPipe Hand Landmarker sarmalayıcısı
  features.py      Parmak durumu, avuç ölçeği, el kimliği
  filters.py       One Euro filtresi, histerezis
  gestures.py      Pinch, el çırpma, menü bekleme tanıyıcıları
  controller.py    Durum makinesi, modlar, eylem üretimi
  mapping.py       Kamera alanını iki monitöre eşleme
  safety.py        Eski örnek reddi, bağımsız zaman aşımı gözcüsü
  dryrun.py        Windows'a dokunmayan sahte alıcı
  config.py        Sürümlü ayar dosyası
  windows/         Win32 bağdaştırıcıları (giriş, pencere, ses, kısayol, oturum)
  ui/              PySide6 tepsi, önizleme, kalibrasyon, ayarlar, katmanlar
  tools/           Konsol kabul testi araçları
tests/             Her modülün kendi klasörü
scripts/           Kurulum, test ve başlatma betikleri
Docs/              Şartname, yol haritası, raporlar
```

Akış: kamera → en yeni kare → takip → özellikler → jestler → denetleyici → eylem → Windows bağdaştırıcısı.

## Belgeler

- [Teknik şartname](Docs/Windows_Hand_Gesture_Control_Spec.md)
- [Yol haritası](Docs/ROADMAP_TR.md)
- [Doküman incelemesi ve kararlar](Docs/DOKUMAN_INCELEME_TR.md)
- [Aşama 0 raporu](Docs/reports/phase0_report.md)
- [Üçüncü taraf lisans bildirimleri](THIRD_PARTY_NOTICES.md)

## Bilinen sınırlar

- Tek RGB kamera, başka bir elin arkasında kalan parmağı göremez. Model tahmini ölçüm sayılmaz; kalite düşünce komutlar askıya alınır.
- Yönetici yetkisiyle çalışan uygulamalar ve korumalı Windows ekranları kapsam dışıdır.
- Yakınlaştırma, hedef uygulamanın Ctrl + tekerlek desteğine bağlıdır.

## Lisans

Projenin kendi kaynak lisansı henüz belirlenmedi. Bu depo özeldir; kamuya dağıtımdan önce lisans netleştirilecektir. Kullanılan üçüncü taraf bileşenlerin lisansları `THIRD_PARTY_NOTICES.md` dosyasındadır.
