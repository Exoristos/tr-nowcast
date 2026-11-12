# DESIGN.md — TR-Nowcast görsel kimlik

**DURUM: KULLANICI KARARI VERİLDİ (2026-11-08).** Kullanıcı Stitch'te kendi tasarımını üretti:
"TR-Nowcast Scientific Terminal" tasarım sistemi (Modern Web Sitesi Tasarımı projesi).
**SCREEN_6 — "Türkçe Nihai Masaüstü Terminali"** ("Kusursuz İstatistiksel Veri Terminali")
`site/assets_root/index.html` olarak repoya alındı. Eşleşen ekranlar: SCREEN_4 = English
Terminal (EN), SCREEN_2 = Mobil Veri Terminali, DESIGN_SYSTEM_1 = token seti.

## Seçilen yön — "Nihai Terminal" (kullanıcı tasarımı)

Sıfat kilidi: **koyu, hairline, mono-ağırlıklı, sessiz, dürüst.**

- Zemin: zinc-950 `#09090b` → yüzeyler `#0c0d10` / `#111217`; hairline kenarlar `#27272a`; radius 0 (keskin).
- Vurgu: emerald `#10b981` (canlı rozet, konsensüs pini, lider kolon) + amber uyarılar; kırmızı `#ef4444` tanımlı (düşüş/hata).
- Tipografi: Inter (gövde) + JetBrains Mono (tüm sayılar/etiketler) + Newsreader (serif rezerv).
- "Renk = kanıt" ilkesi burada emerald ile: canlı durum ve tahmin pini yeşil, nötrler gri.
- Stitch DESIGN_SYSTEM_1 token'ları repoya referans olarak kayıtlıdır (Stitch projesi:
  projects/14414746236348605887).

## Reddedilen eskizler (şef mockup'ları, kullanıcı gördü ve kendi tasarımıyla geçti)

- A — Veri Rasathanesi (bor mavisi) ✗ · B — Kırmızı Çizgi ✗ · C — Anadolu Panosu ✗
- (C'nin kilim dokusu fikri de seçilmedi; kullanıcı terminal yönünü kendisi üretti.)

## Slop denetimi (AGENTS.md listesi — seçilen tasarım üzerinden)

Gradient blob ✗ · glassmorphism ✗ · Inter birincil font (istisna: kullanıcı kararı — mono
hakimiyetiyle terminal kimliği, kabul) · indigo-mor degrade ✗ · hap radius ✗ (yalnız canlı
rozet) · hairline+gölge yığını ✗ (gölge yok, yalnız hairline) · gradient metin ✗ ·
elastic easing ✗ · süs ızgara ✗ (ızgara işlevsel hairline grid)
Denetim yöntemi: Faz 3b sonunda frontend-design-deslop listesi + Playwright ekran kanıtı
(açık/koyu/mobil + konsol 0 hata).

## B seçilirse — kimlik

Sıfat kilidi: **koyu, sessiz, keskin, premium, dürüst.**

### Token'lar (OKLCH)

- Arka plan: `oklch(0.16 0.01 60)` koyu antrasit; yüzey: `oklch(0.21 0.01 60)`
- Metin: `oklch(0.92 0.005 60)`; ikincil metin: `oklch(0.65 0.01 60)`
- **Vurgu (tek):** şarap kırmızısı `oklch(0.45 0.19 20)` — kullanım kuralı: **renk = kanıt**. Yalnız: başlık tahmini, bant kenarları, arena lideri, canlı rozeti. Süs, çizgi, arka plan KULLANMAZ.
- Nötr grafik çubukları/çizgiler: `oklch(0.65 0.01 60)` gri.
- Radius: küçük (4px); hap yok. Kenar: tek hairline yalnız yüzey ayrımında; geniş diffuze gölge yok.
- Hareket: 150-200ms ease-out; elastic/bounce yok.

### Tipografi

- Başlık: Fraunces (Google Fonts) — kişisel siteden farklı ağırlıkta kullanım
- Veri/sayı: JetBrains Mono (tahmin, tablo, eksen)
- Gövde: Space Grotesk

### Sayfa iskeleti (v1)

1. Hero: "Kasım 2026 tahmini" — büyük mono sayı + bant çizimi + türetilmiş yıllık + son güncelleme damgası
2. Model arenası: 8 satırlık dürüst tablo (MAE, iki pencere; kazanan kırmızı, diğerleri gri)
3. Sürücü paneli: USD/TRY, brent, FAO, anket — küçük sparkline'lar
4. Backtest grafiği: tahmin vs gerçek + 80% bant kapsaması
5. Yöntem/dürüstlük bölümü: cutoff kuralı, as-of sözleşmesi (projenin imzası, düz metin)
6. Sohbet (Faz 4 bağlanınca): "verime sor"

### Slop denetimi (AGENTS.md listesi)

Gradient blob/aurora ✗ · glassmorphism ✗ · Inter/Roboto/system-ui ✗ · indigo-mor degrade ✗ · hap radius ✗ ·
hairline+gölge yığını ✗ · gradient metin ✗ · elastic easing ✗ · süs ızgara ✗
Denetim yöntemi: iş bitince frontend-design-deslop listesi + Playwright ekran kanıtı (açık/koyu/mobil + konsol 0 hata).

### TR/EN

İki dil; çeviri sözlüğü gömülü (exoristos.dev v2 düzeni), copy-freeze kuralı: metinler sabit, tasarım bağımsız.
