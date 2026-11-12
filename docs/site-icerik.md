# TR-Nowcast — Site İçeriği (COPY-FREEZE ADAYI)

Tarih: 2026-11-07 · Tüm sayılar data/site/*.json'dan gerçek çıktı. Tasarım bu metinleri
AYNEN taşır; içerik değişirse tasarımın yeniden onayı gerekmez, metin güncellemesidir.

---

## 0. Üst bar

- Marka: **TR-NOWCAST**
- Alt başlık: `Türkiye enflasyonunu, resmî açıklamadan önce tahmin eden açık veri ürünü`
- Rozet: `● canlı — CI her ay otomatik günceller`
- Dil düğmesi: TR | EN

## 1. Hero — güncel tahmin

Başlık: `Kasım 2026 enflasyon tahmini`

- **Aylık: %2,18** (7 modelin medyanı; modellerin bantları: 0,87–2,58 arası)
- **Türetilmiş yıllık: ~%31,5** (bant %29,5–33,3)
- Alt satır: `Hedef ayın verisi TÜİK tarafından ~3 Aralık'ta açıklanacak; bu tahmin 7 Kasım'da yayında olan veriyle üretildi.`
- Küçük dipnot: `Tahmin bantları %80 güven aralığıdır. Gerçek Ekim değeri: %2,58.`

## 2. Model arenası — dürüst skor tablosu

Başlık: `8 yarışmacı, tek sınav, sıfır sızıntı`
Alt metin: `Her model her ay yalnız o güne kadar açıklanmış veriyle sınandı (as-of backtest, 2019→bugün).`

| Model | Kimlik | MAE (2019→bugün) | MAE (son 24 ay) |
|---|---|---|---|
| TCMB beklenti anketi | piyasa uzmanları | **0.85** | **0.48** |
| Chronos-2 | Amazon · zero-shot TSFM | 1.15 | 0.85 |
| Bridge/MIDAS-lite | sürücülü klasik (bizim) | 1.22 | 1.03 |
| ARIMA(1,0,0) | klasik | 1.25 | 1.04 |
| TimesFM 3.0 | Google · çok değişkenli TSFM | 1.25 | **0.82** |
| ETS | klasik | 1.39 | 0.94 |
| Naive | basit çıpa | 1.45 | 1.28 |
| Seasonal-naive | basit çıpa | 1.75 | 0.87 |

İki satırlık okuma (siteye de bu yazılacak):
1. `Son 24 ayda yapay zekâ modelleri (Chronos-2, TimesFM 3.0) klasik istatistiği geçti — TSFM hipotezimiz veriyle doğrulandı.`
2. `Ama şampiyon hâlâ TCMB'nin piyasa anketi: profesyonelleri yenmek için daha çok iş var. Tabloyu olduğu gibi yayımlıyoruz — dürüst kaybetmek şişirilmiş kazanmaktan değerlidir.`

## 3. Sürücü paneli — tahmini besleyen seriler

Başlık: `Tahminin arkasındaki veriler` · her kart: sparkline + son değer + kaynak etiketi

| Seri | Son değer | Kaynak |
|---|---|---|
| USD/TRY | 49,40 (Ekim ort.) | TCMB EVDS |
| Brent (aylık ort.) | 123,93 $ | FRED |
| FAO gıda endeksi | 135,6 (Eylül) | FAO |
| TCMB beklenti anketi | %2,11 (Ekim) | TCMB EVDS |
| TÜFE aylık (gerçek) | %2,58 (Ekim) | TCMB EVDS |

## 4. Backtest grafiği

Başlık: `Tahminler gerçeğe karşı`
Alt metin: `Kesikli çizgi: arenanın medyan tahmini. Dolu çizgi: TÜİK'in açıkladığı gerçek. Gölge: %80 bant.`
Kontroller: model seçici (8 düğme), pencere seçici (2019→ / son 24 ay / tam geçmiş).

## 5. Yöntem — dürüstlük sözleşmesi (projenin imzası)

Başlık: `Bu tabloya neden güvenilir?`
Maddeler (düz metin):
1. Her tahmin yalnız **tahmin gününde yayında olan** veriyle üretilir; gelecekteki hiçbir değer modele gösterilmez — motor, gelecek verisi değişince çıktısının değişmediğini test eden bir sızıntı kanıtıyla korunur.
2. Her veri kaynağının **yayın takvimi kayıtlıdır** (as-of registry) ve sitede gösterilir.
3. Tahmin gününden sonra açıklanan göstergeler (örn. TÜİK gıda endeksi) sürücü olarak kullanılmaz — sızıntı değil, yöntem.
4. Skorlar hangi model kazanırsa kazansın **olduğu gibi yayımlanır**; kod ve veri her şey repoda açık.
5. Bu ürün yatırım tavsiyesi değildir.

## 6. Sohbet — `Verime sor`

Giriş metni: `Bu sitedeki her sayının kaynağını sorabilirsin. Verimde olmayan konularda cevap vermem — aldatmam.`
Örnek çipler: `Kasım tahmini neden bu?` · `Hangi model en iyi?` · `Geçen ay neydi?`
Cevap alanı işaretleri: `kaynak: veri/red` + gerekirse `dikkat: doğrulanamayan sayı` etiketi.

## 7. Alt bar

- `Kod ve veri: github.com/Exoristos/tr-nowcast (public'te yakında)`
- `Yapımcı: Enis Erdoğan — İstatistik öğrencisi, Marmara Üniversitesi`
- `Son güncelleme: <CI damgası> · Kaynaklar: TCMB EVDS · FRED · FAO`
- Bağlantılar: Yöntem · Arena · GitHub · LinkedIn
