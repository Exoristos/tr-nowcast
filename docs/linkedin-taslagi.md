# LinkedIn taslağı — "Arena hikâyesi"

> **Durum:** TASLAK. Yayın yalnızca kullanıcının onayıyla yapılır; bu dosya
> otomatik yayın içermez. Proje linki artık gerçektir: https://exoristos.dev/tr-nowcast
> Sayılar `site/assets_root/scores.json` (2026-11-08 koşumu) ve hero
> verisinden gerçek hesaptır; yayın günü taze koşumla güncellenmeli.

---

**Gönderi metni (TR):**

TÜİK'in aylık enflasyon verisi açıklanmadan önce tahmin üreten açık bir veri
ürünü kurdum: TR-Nowcast. Açık kaynak verilerle (TCMB EVDS, FRED, FAO) ayın
3-8'i arası her gün CI koşuyor, tahmin hileye kapalı bir backtest ile
skorlanıyor ve skorlar kazanan kim olursa olsun olduğu gibi yayınlanıyor.

Arena 8 yarışmacı: klasikler (ARIMA, ETS, naive), benim kurduğum sürücülü
bridge modeli ve zero-shot zaman serisi temel modelleri (Chronos-2, TimesFM
3.0) — artı şampiyona dış ama sahada olan bir rakip: TCMB'nin piyasa
katılımcıları anketi.

İki satırlık okuma (2019'dan bugüne, hileye kapalı as-of backtest):

1. Son 24 ayda yapay zekâ modelleri klasik istatistiği geçti: TimesFM 3.0
   MAE 0,82, Chronos-2 0,85 — ARIMA 1,04, ETS 0,94. Zero-shot mimariler
   Türkiye'nin yapısal rejim değişimlerine klasikten hızlı uyum sağladı.
   TSFM hipotezimiz veriyle doğrulandı.
2. Ama şampiyon hâlâ TCMB'nin piyasa anketi: 2019'dan bugüne MAE 0,85, son
   24 ayda 0,48. Profesyonelleri yenmek için daha çok iş var. Tabloyu olduğu
   gibi yayımlıyoruz — dürüst kaybetmek şişirilmiş kazanmaktan değerlidir.

Kasım 2026 için arenanın medyan tahmini: aylık %2,18, türetilmiş yıllık
~%31,5. Yön isabeti son 12 ayda 96 ay-model çiftinin 70'inde (%73).

Neden güvenilir? Her tahmin yalnız tahmin gününde yayında olan veriyle
üretilir; her kaynağın yayın takvimi kayıtlıdır; TÜİK gıda endeksi TÜFE ile
aynı anda açıklandığı için sürücü olarak kullanılmaz (sızıntı değil,
yöntem); kod ve veri repoda açık.

Proje: https://exoristos.dev/tr-nowcast · Kod ve veri: github.com/Exoristos/tr-nowcast (açık kaynak)

#zamanSerisi #nowcasting #veriBilimi #yapayzeka #istatistik

---

**Yayın notu (gönderiye girmeyecek):**

- Yayın öncesi: `backtest` taze koşulsun, sayılar `scores.json`'dan
  yeniden doğrulansın (ödüllü sayı bayatlamasın).
- Custom domain bağlı (exoristos.dev/tr-nowcast); workers.dev yedek önizleme olarak kalır.
- Ekran görüntüsü ekte: `docs/kanit/tr-masaustu-1440.png`.
