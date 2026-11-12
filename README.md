# trnowcast

TÜİK'in resmî aylık TÜFE'si açıklanmadan *önce*, açık veri kaynaklarından Türkiye enflasyonunu
tahmin eden (nowcasting), canlı yayınlanan bir veri ürünü. Tahminler hileye kapalı bir backtest ile
skorlanır ve TCMB piyasa katılımcıları anketinin "uygun ortalama" beklentisiyle karşılaştırılır.
Tasarım dokümanı: [docs/superpowers/specs/2026-11-05-tr-nowcast-design.md](docs/superpowers/specs/2026-11-05-tr-nowcast-design.md).

## Canlı önizleme

**https://exoristos.dev/tr-nowcast** — ana adres (Cloudflare Worker route: `exoristos.dev/tr-nowcast*`).
Yedek önizleme: <https://tr-nowcast-site.enis-erdogan10.workers.dev> (`workers_dev: true`). Deploy
[.github/workflows/deploy-site.yml](.github/workflows/deploy-site.yml) ile elle
tetiklenir; sohbet canlıdır (MOCK yok). Kanıt: `docs/kanit/` altındaki Playwright
ekran görüntüleri (TR 1440, EN 1440, mobil 390×844) ve `kanit-log.txt`
(konsol 0 hata, gerçek sayı kontrolleri OK).

### Ekran mimarisi

Üç ekran, tek Worker: statik varlıklar + mobil UA yönlendirmesi + `POST /api/sohbet`
(detay: [site/README.md](site/README.md)).

| yol | dil | hedef |
|---|---|---|
| `/` | TR | masaüstü — ana sayfa |
| `/en/` | EN | masaüstü — İngilizce sürüm |
| `/m/` | EN | mobil — tek sayfa; TR mobil sayfa yok (bilinen boşluk, footer'dan masaüstüne dönüş) |

Mobil tarayıcı User-Agent'ı ile `/` istenirse worker `/m/`'ye 302 atar; `/m/`
kendine 302 atmaz (döngü yok). Dil yönlendirmesi yoktur (v1): `/` TR, `/en/` EN.

Veri akışı: CI ayın 3-8'inde `fetch` + `quality` + `nowcast` + `export` koşar;
`trnowcast export` `nowcast.json`, `chart.json`, `series/*.json` ve parquet'ten
özet istatistikleri (`scores.json`) üretip `site/assets_root/`'a kopyalar.
Backtest arenası CI'da koşmaz — skorlar yerelde koşup repoya commit'lenen
`data/processed/backtest_scores.parquet`'ten gelir (yukarıdaki «Model arenası»
bölümü). Sayfalar açılışta same-origin fetch ile bu JSON'ları okur (`site.js`)
ve DOM'u doldurur.

### Yöntem ve dürüstlük (site)

- **Süs sayı yok:** sayfadaki her rakam yukarıdaki JSON'lardan gelir; sahte
  sayı gösterilmek yerine alan kaldırılır. Veri gelmezse boş `--`/0 ile sessiz
  devam edilmez — belirgin hata bandı gösterilir.
- **Yön isabeti tanımı:** isabet = işaret(tahmin − önceki gerçek) ==
  işaret(gerçek − önceki gerçek); parquet'ten hesaplanır, arena genelinde
  havuzlanır (n/n + oran) ve `scores.json`'un `yon_isabet_12m` alanına yazılır.
  12 aylık pencerede medyan MAE (`median_mae_12m`) ve bant içi oran
  (`bant_icinde_12m`) aynı parquet'ten gerçek hesaptır.
- **Grafik gerçek:** SVG çizgi/poligon `chart.json`'dan üretilir; bant poligonu
  gerçek alt/üst uçlarından, nokta sayısı pencere seçimine göre (12/24/tümü).
- **Tek kaynak:** yıllık türetme `nowcast.json`'dan gelir (sayfa yıllığı kendi
  hesaplamaz); hero medyanı ise `nowcast.json`'un `forecasts` listesinden
  tarayıcıda hesaplanır — JSON'da hazır medyan alanı yoktur, ekstra kaynak
  eklenmez.
- **Sohbet sınırı:** `/api/sohbet` yalnız site verisinden derlenen bağlamla
  cevap verir; cevaptaki her sayı bağlamla doğrulanır, doğrulanamayan sayı
  uyarı etiketiyle işaretlenir; yatırım sorusu kod seviyesinde reddedilir.
- Bu ürün yatırım tavsiyesi değildir.

## Kurulum

```bash
uv sync
```

Python ≥ 3.12 gerekir; [uv](https://docs.astral.sh/uv/) bağımlılıkları ve sanal ortamı kurar.

## Komutlar

```bash
uv run trnowcast fetch                  # tüm kaynakları çek, data/processed/ altına yaz
uv run trnowcast fetch --source fred    # tek kaynak: all | fred | fao | tuik | evds
uv run trnowcast status                 # seriler: kaynak, son değer tarihi, satır sayısı, son fetch
uv run trnowcast quality                # tarih sırası, duplicate, NaN oranı, değer aralığı kontrolleri
uv run trnowcast backtest               # model arenası: 8 yarışmacı, skorlar parquet'e yazılır
uv run trnowcast backtest --models classic   # yalnız Faz 1 klasik dörtlüsü (ağ modelleri yüklemez)
```

- `fetch` bir kaynakta hata olursa o kaynağı atlar, diğerlerini sürdürür; yalnız hepsi başarısızsa exit 1 döner.
- `quality` hard-fail varsa exit 1 döner; uyarılar hataya dönüşmez (ör. 2021-2022 enflasyon zirveleri yalnız uyarıdır).
- `backtest --models` seçimi: `classic` (Faz 1 dörtlüsü), `all` (8 yarışmacı — varsayılan) veya virgüllü liste (ör. `naive,bridge`); bilinmeyen ad hata döner.

## Model arenası

`backtest` sekiz yarışmacıyı hileye kapalı as-of kesitlerle koşar; her tahmin
yalnız o ayın cutoff'unda yayında olan veriyi görür (aşağıdaki dürüstlük
sözleşmesi). Skorlar `data/processed/backtest_scores.parquet`'e yazılır.

| model | tip | belirsizlik bandı | not |
|---|---|---|---|
| `naive`, `seasonal_naive` | klasik baseline | tarihsel \|hata\| %80 persentili (min 0.2) | Faz 1 |
| `arima`, `ets` | klasik statsmodels | aynı kural | Faz 1 |
| `chronos2_uni` | Chronos-2 zero-shot (amazon/chronos-2) | 0.1/0.9 quantile | tek değişkenli; torch + GPU ister |
| `timesfm3_mv` | TimesFM 3.0 zero-shot (google/timesfm-3.0-pytorch) | 0.1/0.9 quantile | çok değişkenli: USD/TRY, Brent, FAO gıda sürücüleri geçmiş kovaryatı olarak |
| `bridge` | Bridge / MIDAS-lite (sklearn Ridge) | eğitim artığı %80 persentili (min 0.2) | yorumlanabilir: hedef 1/2/3-ay gecikme + sürücü 1-ay gecikme |
| `anket_pka` | TCMB PKA beklentisi (dış yarışmacı) | tarihsel \|gerçek−anket\| %80 persentili | tahmin değil gözlemlenmiş beklenti; "uygun ortalama", hedef seriyle aynı soru |

**CI TSFM koşmaz:** `chronos2_uni` ve `timesfm3_mv` model ağırlığı indirir ve
GPU ister; GitHub Actions boru hattı TSFM koşmaz — TSFM'li tam koşum yerelde
(`uv run trnowcast backtest --models all`) çalıştırılır ve skor parquet'i
repoya commit'lenir. CI ve zamanlanmış koşum ağ modellerini yüklemeden
`--models classic` ile aynı tabloyu klasik oyuncular için güncelleyebilir.
TSFM ağırlığı ilk kez indirmek ~GB ölçeğinde veri transferidir ve HF cache'e
(repo dışına) iner; `data/raw`'a model dosyası konmaz.

## Veri kaynakları

Ana hedef seri aylık TÜFE'dir: **ana boru EVDS (TCMB)**, TÜİK veri portalı yedektir.
Yedek boru AYRI seri adlarına (`_tuik` soneki) yazar; böylece registry'de satır
bazlı kaynak izi doğru kalır (dürüstlük sözleşmesi md. 2). Yedek borunun canlı
erişimi henüz doğrulanamadı — aşağıdaki «TÜİK yedek boru durumu» bölümüne bakın.

| seri | boru | kaynak | frekans | birim |
|---|---|---|---|---|
| `turkiye_tufe_aylik_yuzde` (ana hedef) | **EVDS — ana boru** | TP.TUKFIY2025.GENEL'den türetilir (aylık % değişim; EVDS'te doğrudan seri yok) | aylık | % |
| `turkiye_tufe_endeks` | **EVDS — ana boru** | TP.TUKFIY2025.GENEL (TÜFE Genel Endeksi, 2025=100) | aylık | endeks |
| `turkiye_tufe_aylik_yuzde_tuik` / `_endeks_tuik` | TÜİK — yedek boru | TÜİK veri portalı TÜFE tabloları — **canlı doğrulanamadı, henüz üretim yok** | aylık | % / endeks |
| `tufe_beklenti_pka` | EVDS — TCMB Piyasa Katılımcıları Anketi | TP.BEK.S01.A.U (uygun ortalama) | aylık | % |
| `usd_try_gunluk` | EVDS | TP.DK.USD.S.YTL | günlük | TL / 1 USD |
| `turkiye_tufe_endeks_fred` | FRED | TURCPIALLMINMEI | aylık | endeks (2015=100) |
| `brent_gunluk` | FRED | DCOILBRENTEU | günlük | USD/varil |
| `fao_gida_endeks` | FAO | FPIS gıda fiyat endeksi | aylık | 2014-2016=100 |

Seri kodları ve veri URL'leri 2026-11-05'te canlı doğrulandı; **istisna TÜİK**:
SDMX uç noktası yalnız resmî dokümantasyondan doğrulandı, canlı indirme
doğrulanamadı (aşağıdaki TÜİK yedek boru durumu). Erişim kaydı her kaynak
modülünün docstring'inde, kaynak üstverisi registry'de tutulur.

### TÜİK yedek boru durumu

Dürüstlük notu (aynı kayıt `tuik.py` docstring'inde): TÜİK SDMX web servisi tüm
isteklerde Bearer token (SMS doğrulamalı API anahtarı) istiyor; bu geliştirme
ortamından canlı indirme doğrulanamadı. Bu yüzden `_tuik` serilerinin henüz
parquet ve registry kaydı yoktur.

- Manuel yol (lokalde çalışır): TÜİK "Tüketici Fiyat Endeksi ve Değişim Oranları"
  tablosunu tarayıcıdan indirip `data/raw/tuik_tufe.xlsx` olarak koyun —
  `fetch` ağa çıkmadan o dosyayı işler.
- GitHub Actions'ta: `data/raw/` gitignored olduğu için manuel yol yoktur;
  zamanlanmış koşuda TÜİK her çalışmada `SourceError` ile atlanır. Boru
  kırılmaz (fetch kaynak hatasında o kaynağı atlar, exit 0 döner) ama TÜİK
  verisi üretilmez.

## EVDS anahtarı

EVDS (TCMB) borusu — USD/TRY kuru, **TÜFE ana serileri** ve beklenti anketi — ücretsiz
bir API anahtarı ister:

1. [evds3.tcmb.gov.tr](https://evds3.tcmb.gov.tr) adresinden üye olup anahtarını alın.
2. Yerelde: `export EVDS_API_KEY="..."` ile ortam değişkeni olarak verin.
3. GitHub Actions'ta: repo **Settings → Secrets and variables → Actions** altına `EVDS_API_KEY` secret'ını ekleyin.

Anahtar yoksa `fetch` evds/anket kaynaklarını bilgilendirip atlar — kalan kaynaklar (fred, fao)
normal çalışır, traceback çıkmaz; bu durumda TÜFE üretilmez (TÜİK yedek boru EVDS anahtarından
bağımsız olarak da atlanır — yukarıdaki TÜİK yedek boru durumu).

## Otomatik güncelleme

[.github/workflows/update.yml](.github/workflows/update.yml) ayın 3-8'inde her gün 06:00 UTC'de
(TÜİK açıklama penceresi) `fetch` + `quality` çalıştırır; kalite kontrolünden geçen **gerçek veri
(parquet) değiştiyse** repoya commit'lenir — registry/fetch_log zaman damgası güncellemeleri tek
başına commit üretmez. GitHub arayüzünden elle tetikleme de mümkündür (workflow_dispatch).
Zamanlanmış koşuda TÜİK yedek boru atlanır (yukarıdaki TÜİK yedek boru durumu); TÜFE ana
borusu EVDS secret ile çalışır.

## Dürüstlük sözleşmesi

Projenin imzası; tam metin tasarım dokümanındadır:

1. Her tahmin yalnız **tahmin gününde yayında olan** veriyle üretilir.
2. Her serinin yayın takvimi kayıt altındadır (as-of registry: kaynak, URL, frekans, yayın gecikmesi).
3. TÜİK gıda endeksi sürücü OLMAZ (TÜFE ile aynı anda açıklanır = sızıntı); FAO gıda fiyat endeksi kullanılır.
4. Ay içi kısmi seriler (dolar, brent) tahmin kesitinde ay ortalamasına kesilir.
5. Backtest expanding-window: her ay yeniden fit/çıkarsama, gelecek verisi sızması yasak.
6. Skorlar hangi model kazanırsa kazansın olduğu gibi yayınlanır.
