// site/tests/wire.test.ts — T26: site.js veri bağlama fonksiyonları (DOM wire).
// Statik fallback yok: veri yüklenemezse hata bandı açılır, sahte sayı yazılmaz.
import { describe, expect, it } from "vitest";
import {
  ayAdi,
  arenaSkorlari,
  cetvelPozisyonlari,
  doldur,
  grafikSVG,
  medyan,
  pencereVerisi,
  sayi,
  sohbetGonder,
  sohbetYaz,
  sparkPuanlari,
  surucuKarti,
  yukleVeDoldur,
  yuzde,
} from "../assets_root/site.js";

// ---- mini sahte DOM: doldur'un kullandığı yalnız yüzey (textContent, innerHTML,
// setAttribute, classList, children/appendChild, querySelector) ----
interface FakeEl {
  tag: string;
  attrs: Record<string, string>;
  children: FakeEl[];
  textContent: string;
  innerHTML: string;
  classSet: Set<string>;
  classList: { toggle(c: string, force?: boolean): void; add(...cs: string[]): void; remove(...cs: string[]): void };
  style: Record<string, string>;
  getAttribute(k: string): string | null;
  setAttribute(k: string, v: string): void;
  appendChild(c: FakeEl): void;
  remove(): void;
  querySelector(sel: string): FakeEl | null;
}

function yeniEl(tag = "div", attrs: Record<string, string> = {}): FakeEl {
  const el: FakeEl = {
    tag,
    attrs: { ...attrs },
    children: [],
    textContent: "",
    innerHTML: "",
    classSet: new Set(attrs.class ? attrs.class.split(/\s+/) : []),
    classList: {
      toggle(c, force) {
        const acik = force !== undefined ? force : !el.classSet.has(c);
        if (acik) el.classSet.add(c);
        else el.classSet.delete(c);
      },
      add(...cs) {
        cs.forEach((c) => el.classSet.add(c));
      },
      remove(...cs) {
        cs.forEach((c) => el.classSet.delete(c));
      },
    },
    style: {},
    getAttribute(k) {
      return k in el.attrs ? el.attrs[k] : null;
    },
    setAttribute(k, v) {
      el.attrs[k] = v;
    },
    appendChild(c) {
      // Gerçek DOM appendChild node'u taşır: aynı ebeveyndeki eski konumdan düş.
      const eski = el.children.indexOf(c);
      if (eski !== -1) el.children.splice(eski, 1);
      el.children.push(c);
    },
    remove() {
      el.attrs.silindi = "1";
    },
    querySelector(sel) {
      if (sel.startsWith("[data-alan=")) {
        const anahtar = sel.slice(12, -2);
        if (el.attrs["data-alan"] === anahtar) return el;
        for (const c of el.children) {
          const bul = c.querySelector(sel);
          if (bul) return bul;
        }
        return null;
      }
      if (sel.startsWith(".")) {
        if (el.classSet.has(sel.slice(1))) return el;
        for (const c of el.children) {
          const bul = c.querySelector(sel);
          if (bul) return bul;
        }
      }
      return null;
    },
  };
  return el;
}

interface FakeDoc {
  documentElement: FakeEl;
  getElementById(id: string): FakeEl | null;
  querySelector(sel: string): FakeEl | null;
}

function fakeDoc(alanlar: Record<string, FakeEl>, ids: Record<string, FakeEl>): FakeDoc {
  const kok = yeniEl("html");
  return {
    documentElement: kok,
    getElementById: (id) => ids[id] ?? null,
    querySelector: (sel) => {
      for (const el of Object.values(alanlar)) {
        const bul = el.querySelector(sel);
        if (bul) return bul;
      }
      return null;
    },
  };
}

function alan(dil: string): FakeEl {
  return yeniEl("span", { "data-alan": dil });
}

// ---- gerçek çıktıya birebir uyan fikstürler (data/site export'u) ----
const GERCEK_FORECASTS = [
  { model: "naive", point: 2.5796108722582645, lower: 0.9221881314975982, upper: 4.237033613018931, ok: true, error: null },
  { model: "seasonal_naive", point: 0.8650220546492449, lower: -0.8013802174264129, upper: 2.5314243267249026, ok: true, error: null },
  { model: "arima", point: 2.1844580923980366, lower: 0.20117143598279452, upper: 4.167744748813279, ok: true, error: null },
  { model: "ets", point: 2.1843539017489477, lower: 0.11325453487015213, upper: 4.255453268627743, ok: true, error: null },
  { model: "chronos2_uni", point: 1.6589463949203491, lower: 0.8740136027336121, upper: 2.8828604221343994, ok: true, error: null },
  { model: "timesfm3_mv", point: 1.6925066709518433, lower: 0.6708962917327881, upper: 3.0677525997161865, ok: true, error: null },
  { model: "bridge", point: 2.2144972360973934, lower: 0.8478084978640559, upper: 3.581185974330731, ok: true, error: null },
  { model: "anket_pka", point: null, lower: null, upper: null, ok: false, error: "anket_pka: 2026-11 anket satırı kesitte yok" },
];

const nowcast = {
  generated_at: "2026-11-08",
  cutoff_date: "2026-11-08",
  target_month: "2026-11",
  forecasts: GERCEK_FORECASTS,
  yillik: { point: 31.466146748031253, lower: 29.51899503000388, upper: 33.26325289221612, temel: "son 11 gerçek ay + hedef tahmini" },
};

const scores = {
  generated_at: "2026-11-08",
  windows: ["2019→bugün", "son 24 ay", "tam geçmiş"],
  scores: [
    { model: "anket_pka", window: "2019→bugün", mae: 0.8524429391178209, rmse: 1.63, n: 94, n_failed: 0, hit80_rate: 0.702 },
    { model: "anket_pka", window: "son 24 ay", mae: 0.47790237139059766, rmse: 0.6, n: 24, n_failed: 0, hit80_rate: 0.791 },
    { model: "naive", window: "2019→bugün", mae: 1.451105739742655, rmse: 2.18, n: 94, n_failed: 0, hit80_rate: 0.68 },
    { model: "naive", window: "son 24 ay", mae: 1.281854019142481, rmse: 1.71, n: 24, n_failed: 0, hit80_rate: 0.666 },
  ],
  median_mae_12m: 0.8702335436938399,
  yon_isabet_12m: { dogru: 70, toplam: 96, oran: 0.7291666666666666 },
  bant_icinde_12m: 0.8020833333333334,
};

const chart = {
  months: ["2026-08-01", "2026-09-01", "2026-10-01"],
  actual: [1.7847526732825525, 1.8404452690166995, 2.5796108722582645],
  forecast_median: [1.761439535207713, 2.0905698413319183, 2.110310567376704],
  band_lo: [0.7971511345956426, 0.807952927469749, 0.8164638338422018],
  band_hi: [3.352950735716946, 3.438706736279954, 3.931461718291913],
  windows: {
    m12: ["2026-08-01", "2026-09-01", "2026-10-01"],
    m24: ["2026-08-01", "2026-09-01", "2026-10-01"],
    all: ["2026-08-01", "2026-09-01", "2026-10-01"],
  },
};

const usdSeri = {
  series: "usd_try_gunluk",
  unit: "TL (1 USD karşılığı)",
  points: [
    ["2026-09-01", 48.60608181818182],
    ["2026-10-01", 49.40002380952381],
  ],
};

describe("biçimlendirme", () => {
  it("sayı TR'de virgül, EN'de nokta", () => {
    expect(sayi(2.1845, 2, "tr")).toBe("2,18");
    expect(sayi(2.1845, 2, "en")).toBe("2.18");
    expect(sayi(null, 2, "tr")).toBe("—");
  });
  it("yüzde TR'de önek, EN'de sonek (değer yüzde birimi; oran çağıran tarafta ×100)", () => {
    expect(yuzde(72.91666666666666, 1, "tr")).toBe("%72,9");
    expect(yuzde(80.20833333333334, 1, "en")).toBe("80.2%");
  });
  it("ay adı kısa/uzun", () => {
    expect(ayAdi("2026-10-01", "tr")).toBe("Ekim");
    expect(ayAdi("2026-12-01", "tr", true)).toBe("Ara");
    expect(ayAdi("2026-12-01", "en", true)).toBe("Dec");
  });
  it("medyan tek/çift eleman", () => {
    expect(medyan([1, 3, 2])).toBe(2);
    expect(medyan([4, 1, 3, 2])).toBe(2.5);
  });
});

describe("pencere ve cetvel", () => {
  it("pencereVerisi dizileri pencere aylarına göre dilimler", () => {
    const p = pencereVerisi(chart, "m12");
    expect(p.aylar).toHaveLength(3);
    expect(p.gercek[2]).toBe(2.5796108722582645);
    expect(p.hi[2]).toBeCloseTo(3.931461718291913, 10);
  });
  it("cetvel gerçek medyan/min/max ve model adlarını verir", () => {
    const c = cetvelPozisyonlari(nowcast);
    // 7 puanın medyanı: sıralı dizide 4'üncü = ets (2,18435) → %2,18
    expect(c.med).toBeCloseTo(2.1843539017489477, 10);
    expect(c.min).toBeCloseTo(0.8650220546492449, 10);
    expect(c.max).toBeCloseTo(2.5796108722582645, 10);
    expect(c.minModel).toBe("seasonal_naive");
    expect(c.maxModel).toBe("naive");
    expect(c.pinPos).toBeGreaterThan(c.spanBaslangic);
    expect(c.pinPos).toBeLessThanOrEqual(100);
  });
});

describe("grafik ve sparkline", () => {
  it("grafikSVG bant poligonu, iki çizgi ve pimi üretir", () => {
    const svg = grafikSVG(chart, nowcast, "m12", "tr");
    expect(svg).toContain("<polygon");
    expect(svg).toContain('stroke="#f4f4f5"');
    expect(svg).toContain('stroke="#71717a"');
    expect(svg).toContain("%2,18 (Tahmin)");
    expect(svg).toContain("%2,58 (Ekim)");
    expect((svg.match(/<polyline/g) ?? []).length).toBe(2);
  });
  it("sparkPuanlari son n noktayı 100x24 alanına normalize eder", () => {
    const noktalar = Array.from({ length: 20 }, (_, i) => [`2025-${String((i % 12) + 1).padStart(2, "0")}-01`, i] as [string, number]);
    const p = sparkPuanlari(noktalar, 12);
    const ciftler = p.trim().split(" ").map((c: string) => c.split(",").map(Number));
    expect(ciftler).toHaveLength(12);
    for (const [x, y] of ciftler) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(100);
      expect(y).toBeGreaterThanOrEqual(2);
      expect(y).toBeLessThanOrEqual(22);
    }
    // artan seri → y monotonic azalır (yukarı doğru çizgi)
    expect(ciftler[11][1]).toBeLessThan(ciftler[0][1]);
  });
});

describe("sürücü kartı ve arena", () => {
  it("USD kartı gerçek son değer ve m/m deltası", () => {
    const k = surucuKarti("usd_aylik", usdSeri, "tr", false);
    expect(k.deger).toBe("49,40");
    expect(k.delta).toBe("+1,6% M/M");
    expect(k.yon).toBe(1);
    expect(k.ayEtiketi).toContain("Ekim");
  });
  it("anket kartı pp farkı kullanır", () => {
    const seri = { series: "tufe_beklenti_pka", unit: "%", points: [["2026-09-01", 2.12], ["2026-10-01", 2.11]] as [string, number][] };
    const k = surucuKarti("anket_pka", seri, "tr", false);
    expect(k.delta).toBe("-0,01 p M/M");
    expect(k.deger).toBe("%2,11");
  });
  it("arenaSkorlari pencereleri modele eşler", () => {
    // site.js JS olduğundan dönüş tipi çıkarılamaz; şekil burada sabitlenir.
    const s = arenaSkorlari(scores) as Record<string, { tum: number; son24: number }>;
    expect(s.anket_pka.tum).toBeCloseTo(0.8524429391178209, 10);
    expect(s.anket_pka.son24).toBeCloseTo(0.47790237139059766, 10);
  });
});

function ornekTbody(): FakeEl {
  const tbody = yeniEl("tbody");
  for (const model of ["naive", "anket_pka"]) {
    const tr = yeniEl("tr", { "data-model": model });
    tr.appendChild(yeniEl("td", { class: "row-idx" }));
    tr.appendChild(yeniEl("td", { "data-alan": "mae-all" }));
    tr.appendChild(yeniEl("td", { "data-alan": "mae-24" }));
    tbody.appendChild(tr);
  }
  return tbody;
}

function hazirla() {
    const alanlar: Record<string, FakeEl> = {};
    for (const k of [
      "son-calistirma", "rapor-ay", "aciklama-tarih", "aciklama-kutu", "hero-ay",
      "nowcast-deger", "nowcast-delta", "onceki-gercek", "yillik-deger", "yillik-bant",
      "model-sayisi", "yayilim", "cetvel-olcek", "cetvel-min-deger", "cetvel-medyan-deger",
      "cetvel-max-deger", "cetvel-min-model", "cetvel-max-model", "stat-mae-12", "stat-yon",
      "stat-bant", "lider-mae", "usd_aylik-deger", "usd_aylik-delta", "usd_aylik-ay",
      "usd_aylik-spark", "tufe_aylik-deger", "grafik-not",
    ]) {
      alanlar[k] = alan(k);
    }
    const cetvelSpan = yeniEl("div", { "data-alan": "cetvel-span" });
    alanlar["cetvel-span"] = cetvelSpan;
    const grafik = yeniEl("svg");
    grafik.setAttribute("id", "tahmin-grafik");
    const tbody = ornekTbody();
    const ids: Record<string, FakeEl> = { "tahmin-grafik": grafik, "models-tbody": tbody };
    const doc = fakeDoc(alanlar, ids);
    return { doc, alanlar, grafik, tbody, ids };
}

describe("doldur", () => {
  it("hero, istatistik satırı ve tabloyu gerçek veriyle doldurur", () => {
    const { doc, alanlar, grafik, tbody } = hazirla();
    doldur(doc, { nowcast, scores, chart, seriler: { usd_aylik: usdSeri } }, "tr", false);
    expect(alanlar["nowcast-deger"].textContent).toBe("%2,18");
    expect(alanlar["nowcast-delta"].textContent).toContain("-0,40");
    expect(alanlar["onceki-gercek"].textContent).toContain("2,58");
    expect(alanlar["yillik-deger"].textContent).toBe("~%31,5");
    expect(alanlar["model-sayisi"].textContent).toBe("7");
    expect(alanlar["yayilim"].textContent).toContain("0,87");
    expect(alanlar["son-calistirma"].textContent).toBe("2026-11-08");
    expect(alanlar["stat-mae-12"].textContent).toBe("0,87 puan");
    expect(alanlar["stat-yon"].textContent).toBe("%72,9 (70/96)");
    expect(alanlar["stat-bant"].textContent).toBe("%80,2");
    expect(alanlar["usd_aylik-deger"].textContent).toBe("49,40");
    expect(alanlar["usd_aylik-spark"].getAttribute("points")).toContain(",");
    // tablo: anket önce gelir (mae-24 0,48 < 1,28), hücreler JSON'dan
    const ilkSatir = tbody.children.find((r) => r.getAttribute("data-model") === "anket_pka");
    expect(ilkSatir).toBeDefined();
    expect(tbody.children[0].getAttribute("data-model")).toBe("anket_pka");
    expect(ilkSatir!.querySelector('[data-alan="mae-all"]')!.textContent).toBe("0,85");
    expect(ilkSatir!.querySelector('[data-alan="mae-24"]')!.textContent).toBe("0,48");
    expect(grafik.innerHTML).toContain("<polygon");
    // grafik dipnotu hedef ayı veriden alır (statik ay iddiası yok)
    expect(alanlar["grafik-not"].textContent).toBe("*Kasım ayı resmî açıklaması bekleniyor");
    // cetvel pin/span pozisyonu veriye bağlı
    expect(parseFloat(alanlar["cetvel-span"].style.left)).toBeGreaterThanOrEqual(0);
    expect(parseFloat(alanlar["cetvel-span"].style.width)).toBeGreaterThan(0);
  });

  it("oran/bant alanları null ise sahte sıfır yerine '—' gösterir", () => {
    const { doc, alanlar } = hazirla();
    const scoresBos = {
      ...scores,
      median_mae_12m: null,
      yon_isabet_12m: { dogru: 0, toplam: 0, oran: null },
      bant_icinde_12m: null,
    };
    doldur(doc, { nowcast, scores: scoresBos, chart, seriler: {} }, "tr", false);
    expect(alanlar["stat-yon"].textContent).toBe("—");
    expect(alanlar["stat-bant"].textContent).toBe("—");
    expect(alanlar["stat-mae-12"].textContent).toBe("— puan");
  });
});

describe("yukleVeDoldur", () => {
  // Anahtarlar artık göreli: doldur.js yolları <base> ile dağıtım köküne çözer.
  const VERILER: Record<string, unknown> = {
    "nowcast.json": nowcast,
    "scores.json": scores,
    "chart.json": chart,
    "series/usd_aylik.json": usdSeri,
    "series/brent_aylik.json": { series: "brent_gunluk", unit: "USD", points: [["2026-09-01", 114.159], ["2026-10-01", 123.927]] },
    "series/fao_aylik.json": { series: "fao_gida_endeks", unit: "idx", points: [["2026-08-01", 133.9], ["2026-09-01", 135.6]] },
    "series/anket_pka.json": { series: "tufe_beklenti_pka", unit: "%", points: [["2026-09-01", 2.12], ["2026-10-01", 2.11]] },
    "series/tufe_aylik.json": { series: "turkiye_tufe_aylik_yuzde", unit: "%", points: [["2026-09-01", 1.84], ["2026-10-01", 2.5796]] },
  };

  it("tüm kaynaklar gelirse sayfayı doldurur ve bant gizli kalır", async () => {
    const { doc, alanlar, ids } = hazirla();
    ids["veri-hatasi"] = yeniEl("div", { class: "hidden" });
    const getir = async (yol: string) => {
      if (!(yol in VERILER)) throw new Error("404");
      return VERILER[yol];
    };
    const veri = await yukleVeDoldur(doc, getir, "tr", false);
    expect(veri).not.toBeNull();
    expect(alanlar["nowcast-deger"].textContent).toBe("%2,18");
    expect(ids["veri-hatasi"]!.classSet.has("hidden")).toBe(true);
  });

  it("200 OK dönen şeması bozuk JSON'da hata bandı açılır, sessiz '…' kalınmaz", async () => {
    const { doc, alanlar, ids } = hazirla();
    const bant = yeniEl("div", { class: "hidden" });
    ids["veri-hatasi"] = bant;
    const getir = async (yol: string) => {
      if (yol === "nowcast.json") return { generated_at: "2026-11-08", target_month: "2026-11" }; // forecasts yok
      return VERILER[yol];
    };
    const veri = await yukleVeDoldur(doc, getir, "tr", false);
    expect(veri).toBeNull();
    expect(bant.classSet.has("hidden")).toBe(false);
    expect(bant.textContent).toContain("şema");
    expect(alanlar["nowcast-deger"].textContent).toBe("");
  });

  it("bir kaynak 404 ise hata bandı açılır, sayı yazılmaz", async () => {
    const { doc, alanlar, ids } = hazirla();
    const bant = yeniEl("div", { class: "hidden" });
    ids["veri-hatasi"] = bant;
    const getir = async (yol: string) => {
      if (yol === "scores.json") throw new Error("404");
      return VERILER[yol];
    };
    await yukleVeDoldur(doc, getir, "tr", false);
    expect(bant.classSet.has("hidden")).toBe(false);
    expect(bant.textContent).toContain("scores.json");
    expect(alanlar["nowcast-deger"].textContent).toBe("");
  });
});

describe("sohbet", () => {
  it("POST /api/sohbet gövdesi {soru} olur", async () => {
    let yakalanan: { yol: string; secenek?: RequestInit } | null = null;
    const getir = async (yol: string, secenek?: RequestInit) => {
      yakalanan = { yol, secenek };
      return { cevap: "Kasım tahmini 7 modelin medyanıdır.", kaynak: "veri", dikkat: null };
    };
    const yanit = await sohbetGonder(getir, "Kasım tahmini neden bu?");
    expect(yakalanan!.yol).toBe("api/sohbet");
    expect(yakalanan!.secenek!.method).toBe("POST");
    expect(JSON.parse(String(yakalanan!.secenek!.body))).toEqual({ soru: "Kasım tahmini neden bu?" });
    expect(yanit.cevap).toContain("medyan");
  });

  it("sohbetYaz kaynak/dikkat etiketlerini basar, HTML kaçırr", () => {
    const el = yeniEl("div", { class: "hidden" });
    sohbetYaz(el, { cevap: "<img>x", kaynak: "veri", dikkat: "doğrulanamayan sayı" });
    expect(el.innerHTML).toContain("&lt;img&gt;");
    expect(el.innerHTML).toContain("kaynak: veri");
    expect(el.innerHTML).toContain("dikkat: doğrulanamayan sayı");
    sohbetYaz(el, { hata: "bağlantı kurulamadı" });
    expect(el.innerHTML).toContain("bağlantı kurulamadı");
  });
});
