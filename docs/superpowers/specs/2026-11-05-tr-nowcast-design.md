# TR-Nowcast — Tasarım Dokümanı

Tarih: 2026-11-05 · Durum: onaylandı (kullanıcı, plan onayıyla) · Sahip: Enis Erdoğan (exoristos)

## Amaç ve neden

Enis, LinkedIn'e koyacağı, üç role de (veri analisti / veri bilimci / AI geliştirici) "bunu almalıyız"
dedirtecek, canlı linkli TEK portfolyo projesi istiyor. beyin-rag portfolyonun 1. projesi; bu 2. proje
olarak staj hedefindeki "README'li 2 proje" şartını tamamlar.

**Ürün cümlesi:** TÜİK'in resmî aylık TÜFE'si açıklanmadan *önce*, açık veri kaynaklarından Türkiye
enflasyonunu tahmin eden (nowcasting), canlı yayınlanan bir veri ürünü. Tahminler hileye kapalı bir
backtest ile skorlanır ve TCMB piyasa katılımcıları anketinin "uygun ortalama" beklentisiyle karşılaştırılır.

## Hedefler

- Canlı yayınlanan site (Cloudflare; mevcut exoristos.dev altyapısı üzerine)
- Dürüst backtest: her ay yalnız o ana kadar bilinen veriyle üretim; nokta tahmin + belirsizlik bandı
- Model arenası:
  1. Klasik benchmarklar: naive, seasonal-naive, ARIMA/ETS (tek değişkenli)
  2. Chronos-2 zero-shot (Amazon, 120M) — tek değişkenli mod
  3. TimesFM 3.0 çok değişkenli + kovaryat (Google, 330M) — flaş model; sürücüler geçmiş kovaryat,
     açıklaması yapılmış olaylar (asgari ücret, tarife) "bilinen gelecek kovaryat"
  4. Klasik bridge/MIDAS-lite — yorumlanabilir karşılaştırıcı
  5. TCMB Piyasa Katılımcıları Anketi uygun ortalaması (EVDS TP.BEK.S01.A.U; T10 düzeltmesi:
     medyan değil, "uygun ortalama" — kanıt ve geçmiş için survey.py docstring'i) — dış benchmark
- Doğal dil sohbet ekranı (Cloudflare Workers AI), yalnız projedeki veriyle cevap
- README: yöntem, dürüstlük kuralları, skorlar; LinkedIn gönderisi (yayın kullanıcı onayına bağlı)

## Hedef değişken (kullanıcı kararı)

Ana hedef **aylık TÜFE % değişim**. Yıllık TÜFE sitede aylık seriden türetilmiş olarak gösterilir.

## Sınav dönemi (kullanıcı kararı — "karışım")

- Modellerin **girdisi** her zaman tüm kullanılabilir geçmiş.
- **Ana skor** 2019→bugün; ayrıca "son 24 ay" alt skoru; README ekinde tam geçmiş tablosu.
- Gerekçe: Türkiye enflasyonu durağan değil; rejimleri havuzlayan tek sayı hiçbir dönemi anlatmaz.

## Dürüstlük sözleşmesi (projenin imzası)

1. Her tahmin yalnız **tahmin gününde yayında olan** veriyle üretilir.
2. Her serinin yayın takvimi kayıt altındadır (as-of registry: kaynak, URL, frekans, yayın gecikmesi).
3. TÜİK gıda endeksi sürücü OLMAZ (TÜFE ile aynı anda açıklanır = sızıntı). Yerine FAO gıda fiyat
   endeksi gibi tahmin gününden önce yayında olan kaynaklar.
4. Ay içi kısmi seriler (dolar, brent) tahmin kesitinde ay ortalamasına kesilir.
5. Backtest expanding-window: her ay yeniden fit/çıkarsama, gelecek verisi sızması yasak.
6. Skorlar hangi model kazanırsa kazansın olduğu gibi yayınlanır; dürüst kaybetme şişirilmiş
   kazanmadan kıymetlidir.

## Olmayanlar / anti-hedefler

- Yatırım tavsiyesi, al-sat sinyali (o domain AI-Quant-Trading'in)
- Gerçek zamanlı streaming; aylık/haftalık kadans
- Kullanıcı hesapları; site herkese açık salt-okunur
- Anti: hileli backtest (tek gerçek ölüm hali), tutorial klonu görünümü, tek kaynağa bağımlılık
  (TÜİK → FRED TURCPIALLMINMEI yedek zinciri zorunlu)

## Kısıtlar

- Veri: TCMB EVDS ücretsiz API (kullanıcı kaydı + anahtar); FRED anahtarsız CSV; TÜİK indirilebilir
  dosya; FAO yayın dosyası; TCMB anketi EVDS/web.
- Donanım: RTX 4070 laptop — TSFM inference + küçük fine-tune yeterli.
- Stack: Python (uv), torch + chronos-2 + timesfm, statsmodels/sklearn; model lokalde/CI'da çalışır,
  çıktılar JSON → statik site + hafif Cloudflare Worker; sohbet Workers AI.
- Otomasyon: GitHub Actions zamanlanmış boru hattı (EVDS anahtarı secret); ağır işler lokalde.
- Repo: ~/Projelerim/tr-nowcast. Çalışma düzeni: şef + alt ajan havuzu (AGENTS.md); kullanıcı kod
  yazmaz, karar verir. Mimosa hook'u nedeniyle dosya yazımı Write/Edit araçlarıyla.

## Yaklaşımlar (düşünülen, reddedilen)

1. Tek büyük model: TSFM'i her şeyi yapacak şekilde fine-tune — RED: sürücü körlüğü, küçük TR
   verisiyle overfit riski, zayıf hikâye.
2. Yalnız klasik nowcast (MIDAS/bridge) — RED: AI katmanı ve TSFM wow'u kaybolur.
3. Model yarışı + dürüst eval + canlı ürün — SEÇİLEN: üç role de kesen tek şekil.
4. Alternatif domain: BIST analitik ürünü — kullanıcı enflasyon nowcasting'i seçti.

## Fazlar

| Faz | İçerik | Çıkış |
|-----|--------|-------|
| 0 | Repo + veri hattı (EVDS, FRED, TÜİK, FAO, anket) + depo + kalite testleri | tek komutla idempotent güncel veri |
| 1 | Backtest çerçevesi + klasik benchmarklar | CLI skor tablosu |
| 2 | Chronos-2 + TimesFM 3.0 + bridge + anket kıyası | tam yarış tablosu |
| 3 | Önyüz v1 canlı (DESIGN.md onaylı) | exoristos.dev altında canlı site |
| 4 | Workers AI sohbet katmanı | veriye bağlı sohbet |
| 5 | Stretch: BIST'le fine-tune (kill criterion'lu) + README + LinkedIn + kart | lansman |

## Görsel kimlik

Karanlık premium tonlar; tek vurgu rengi "renk = kanıt" ilkesine bağlı; OKLCH; yasaklı klişeler
(gradient blob, dekoratif glassmorphism, hap kolonisi, hairline+diffuze gölge yığını vb. AGENTS.md
listesi). Detaylar Faz 3 başında repo kökünde DESIGN.md olarak yazılır ve kullanıcı onayına sunulur.

## Builder-check kaydı (2026-11-05)

Bağımsız denetçi 6 açık nokta buldu; kapanış şekli:
1. Hedef metrik (aylık/yıllık) → kullanıcı: "ikisi de" (aylık ana, yıllık türetilmiş)
2. Kesit tarihi kuralı → dürüstlük sözleşmesi maddeleri 1-4
3. Gıda sürücüsü kaynağı → madde 3 (TÜİK gıda yasak, FAO öncelikli)
4. Backtest dönemi → kullanıcı: karışım (yukarıda)
5. Otomasyon mimarisi → GitHub Actions primary, lokal fallback
6. Fine-tune amacı/verisi → Faz 5'te veri denetimi önce, kill criterion yazılı (BIST serileriyle
   domain adaptasyonu, TÜFE'de sınama)

## Builder'a bırakılanlar

Sayfa bileşenleri, grafik kütüphanesi, klasik model hiperparametreleri, fine-tune config'i,
deploy ayrıntıları, serinin kesin EVDS kodlarının doğrulanması.
