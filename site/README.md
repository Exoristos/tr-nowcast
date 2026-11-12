# site/ — Cloudflare Worker (assets + mobil yönlendirme + `/api/sohbet`)

Worker statik dosyaları servis eder, mobil tarayıcıyı `/m/`'ye yönlendirir ve
sohbet endpoint'i barındırır (`src/worker.ts`, `src/prompt.ts`, `src/dogrula.ts`).
Veri kaynağı `trnowcast export` çıktısı (`data/site/`); veri güncellemesi = yeni
commit, deploy `.github/workflows/deploy-site.yml` ile workers.dev'e yapılır.

## Dosyalar

- `wrangler.jsonc` — worker yapılandırması (assets kökü: `assets_root/`, `ai` binding,
  `workers_dev: true`; MOCK var'ı kaldırıldı — sohbet canlı)
- `src/worker.ts` — fetch handler: mobil UA yönlendirme + assets passthrough + `POST /api/sohbet`
- `src/prompt.ts` — prompt derleyici, konu sınıflandırıcılar, sabit red şablonları
- `src/dogrula.ts` — çıkış sayı doğrulama katmanı (guardrail)
- `assets_root/index.html` — yer tutucu sayfa (görsel önyüz sonraki fazda);
  commit'lenir, böylece taze checkout'ta wrangler dry-run statik dosya bulur
- `assets_root/` içindeki JSON/series dosyaları — `trnowcast export` deploy
  öncesi günceller; `assets_root/` tamamen git izlemesindedir (Stitch kaynak
  sayfaları + CI'nin kopyaladığı site verisi birlikte commit'lenir,
  bkz. `.gitignore`)

## POST `/api/sohbet` — sözleşme

Gövde: `{"soru": string}` (boş olmayan metin). Başarılı yanıt 200:

| Alan | Tip | Açıklama |
|---|---|---|
| `cevap` | string | Asistan yanıtı (soru dilinde) |
| `kaynak` | `"veri"` \| `"red"` \| `"tavsiye_redi"` | Yanıtın geldiği katman |
| `dikkat` | string \| null | Sayı doğrulama uyarısı; `"cevapta doğrulanamayan sayı var"` dolu geldiğinde cevap güvenilir değil sayılmalıdır |

Hata yanıtı: `{"hata": string}` — 400 (gövde/soru geçersiz), 405 (POST değil),
500 (beklenmedik), 502 (LLM çağrısı başarısız veya boş), 503 (site verisi
yüklenemedi/şema dışı).

## Guardrail davranışı

| Katman | Davranış |
|---|---|
| System prompt | LLM yalnız BAĞLAM bölümündeki veriyi kullanır; bağlamda olmayan konuda "verimde yok" der |
| Bağlam kaynağı | Prompt metni yalnız `data/site/*.json`'dan derlenir (`derle`); başka kaynak giremez |
| Sayı doğrulama | Cevaptaki her sayı yalnız BAĞLAM bölümüyle karşılaştırılır (`dogrula`); kullanıcının sorusuna gömdüğü sayılar doğrulanmış sayılmaz. Bağlamda olmayan sayı → `dikkat: "cevapta doğrulanamayan sayı var"`, sessiz geçilmez |
| Tavsiye kalkanı | Yatırım/alım-satım sorusu LLM'e hiç gitmez; kod seviyesinde sabit `TAVSIYE_REDI` şablonu döner (`kaynak: "tavsiye_redi"`) |
| Kesinlik şablonu | "Kesin mi?" sorusu bant + MAE ile belirsizliği anlatan şablonla yanıtlanır; kesinlik iddiası diline cevap verilemez. Şablonun sabiti olan %80 yalnız bu cevap için beyaz listelenir |
| Veri-dışı red | Veride olmayan konu sorulursa cevap veri-dışı red kalıbıyla döner (`kaynak: "red"`); bağlama veri-dışı sayı sızmaz |
| MOCK=1 | LLM çağrısı hiç yapılmaz: veri sorusunda derlenen bağlam özeti, aksi halde veri-dışı red döner (CI/yerel testler bununla koşar) |

## Mobil UA yönlendirme

TR masaüstü sayfası (`/` ve `/index.html`) mobil tarayıcı User-Agent'ı ile
istendiğinde `/m/`'ye 302 ile yönlendirilir. `/m/` yol koşula uymadığı için
kendine 302 atmaz (döngü yok); `/en/` ve varlıklar (`/site.js` vb.)
yönlendirilmez. TR mobil sayfası yoktur — `/m/` EN mobildir; bilinen boşluk,
footer'daki link ile masaüstüne döner.

## Deploy (workers.dev önizlemesi)

Deploy **yalnız workers.dev'e** yapılır; custom domain (exoristos.dev) ayrı
onay konusudur. Deploy `.github/workflows/deploy-site.yml` (workflow_dispatch)
ile: build + vitest → `trnowcast export` çıktısı `assets_root/`'a kopyalanır →
`wrangler deploy`.

**Canlı önizleme:** https://tr-nowcast-site.enis-erdogan10.workers.dev

Sohbet canlıdır: deploy edilen worker'da `MOCK` var'ı tanımlı değildir;
`/api/sohbet` gerçek LLM binding'ini çağırır. MOCK kod yolu yalnız vitest
ortamında (mock env) koşar.

Deploy sonrası smoke: `curl -s -o /dev/null -w '%{http_code}' <URL>/` → 200 ve
`curl -s <URL>/nowcast.json` → 200 beklenir.

## Playwright kanıtı (docs/kanit/)

Ekran görüntüleri ve gerçek sayı kontrolleri `kanit.py` ile üretilir; script
varsayılan olarak yukarıdaki canlı URL'e bağlanır, başka URL argümanla verilir:

```bash
python3 site/kanit.py | tee docs/kanit/kanit-log.txt
```

Gereksinim: `pip install playwright && playwright install chromium`. Script her
koşumda PNG'leri (`tr-masaustu-1440.png`, `en-masaustu-1440.png`,
`mobil-390x844.png`) yeniler ve konsol hatası, hero/yıllık/anket MAE değerleri
ile sparkline/grafik varlığını JSON kaynaklarıyla karşılaştırıp loga yazar.

## Yerel doğrulama (deploy değil)

```bash
cd site
npx wrangler deploy --dry-run --outdir dist
```

Exit 0 beklenir. Gerçek deploy (`npx wrangler deploy`) yalnızca kullanıcı
onayından sonra çalıştırılır.

## Veri şemaları (`data/site/`, `trnowcast export` üretir)

Tüm JSON alan adları snake_case, tarihler ISO. Tarihler ay-başı (`YYYY-MM-DD`),
sayılar kayan nokta.

### `nowcast.json`

Güncel ay canlı nowcast (8 model) + türetilmiş yıllık.

| Alan | Tip | Açıklama |
|---|---|---|
| `generated_at` | string (ISO tarih) | Üretim tarihi |
| `cutoff_date` | string (ISO tarih) | Motorun as-of kesiti (komut anı) |
| `target_month` | string (`YYYY-MM`) | Tahmin edilen ay |
| `forecasts[]` | dizi | Model başına bir kayıt |
| `forecasts[].model` | string | Model adı |
| `forecasts[].point` | number \| null | Nokta tahmin (aylık %) |
| `forecasts[].lower` | number \| null | %80 bandın alt ucu |
| `forecasts[].upper` | number \| null | %80 bandın üst ucu |
| `forecasts[].ok` | bool | Model başarılı mı (başarısızlık normal iş akışı) |
| `forecasts[].error` | string \| null | `ok: false` ise hata iletisi |
| `yillik` | object \| null | Türetilmiş 12 aylık yıllık; gerçek ay < 11 ise `null` |
| `yillik.point` / `.lower` / `.upper` | number | Kümülatif formülle türetilmiş yıllık (%) |
| `yillik.temel` | string | Türetme temelinin insan-okur özeti |

### `scores.json`

Faz 1 backtest skor tablosu, üç pencere.

| Alan | Tip | Açıklama |
|---|---|---|
| `generated_at` | string (ISO tarih) | Üretim tarihi |
| `windows[]` | string dizisi | Pencere adları (ör. `2019→bugün`) |
| `scores[]` | dizi | Model × pencere başına bir kayıt |
| `scores[].model` | string | Model adı |
| `scores[].window` | string | Pencere adı |
| `scores[].mae` / `.rmse` | number | Hata metrikleri (aylık %) |
| `scores[].n` | int | Değerlendirilen ay sayısı |
| `scores[].n_failed` | int | Başarısız model-ay sayısı |
| `scores[].hit80_rate` | number | %80 bant isabet oranı (0–1) |

### `series/*.json`

`tufe_aylik`, `usd_aylik`, `brent_aylik`, `fao_aylik`, `anket_pka` — site
grafiklerinin hammaddesi.

| Alan | Tip | Açıklama |
|---|---|---|
| `series` | string | Seri adı (registry kimliği) |
| `unit` | string | Birim (ör. `% (aylık, türetilmiş)`) |
| `points[]` | `[ISO tarih, number]` dizisi | Ay-başı ISO tarih + değer; tarihe göre artan sıralı |

### `meta.json`

| Alan | Tip | Açıklama |
|---|---|---|
| `generated_at` | string (ISO tarih) | Üretim tarihi |
| `registry` | object | Seri adı → kaynak kaydı (`source`, `url`, `frequency`, `units`, `publication_lag_days`, `license_note`, …) |
