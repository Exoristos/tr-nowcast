// site/assets_root/doldur.js — JSON verisini data-alan noktalarına yazan katman (T26).
// Statik fallback yok: kaynak başarısızsa hata bandı açılır, sahte sayı yazılmaz.
import { ayAdi, medyan, sayi, yuzde } from "./bicim.js";
import { grafikSVG } from "./grafik.js";
import { MODEL, SERILER, cetvelPozisyonlari, sparkPuanlari, sonrakiAyIso, surucuKarti, arenaSkorlari, tabloSirala } from "./kartlar.js";

// Yollar sayfa-tabanlı göreli: HTML'lerdeki <base> etiketi bunları dağıtım köküne
// çözer (workers.dev kökü veya /tr-nowcast/), böylece iki tabanda aynı dosyalar bulunur.
const ADRESLER = ["nowcast.json", "scores.json", "chart.json", ...SERILER.map((a) => `series/${a}.json`)];

function yaz(doc, key, metin) {
  const el = doc.querySelector(`[data-alan="${key}"]`);
  if (el) el.textContent = metin;
}

function aciklamaMetni(hedef, dil, kisa, saat) {
  const iso = sonrakiAyIso(hedef);
  if (kisa) return saat ? `~${ayAdi(iso, dil, true)} 3, 10:00` : `~${ayAdi(iso, dil, true)} 3, ${iso.slice(0, 4)}`;
  if (dil === "tr") return `~3 ${ayAdi(iso, "tr")} ${iso.slice(0, 4)}${saat ? " 10:00" : ""}`;
  return `~${ayAdi(iso, "en")} 3, ${iso.slice(0, 4)}${saat ? " 10:00" : ""}`;
}

export function doldur(doc, veri, dil, kisa) {
  const { nowcast, scores, chart, seriler } = veri;
  const ok = nowcast.forecasts.filter((f) => f.ok && f.point !== null);
  const puanlar = ok.map((f) => f.point);
  const orta = medyan(puanlar);
  const ayIso = `${nowcast.target_month}-01`;

  yaz(doc, "son-calistirma", nowcast.generated_at);
  if (dil === "tr") yaz(doc, "rapor-ay", `${ayAdi(ayIso, "tr").toUpperCase()} ${nowcast.target_month.slice(0, 4)} GÖSTERGE RAPORU`);
  else yaz(doc, "rapor-ay", `${ayAdi(ayIso, "en").toUpperCase()} ${nowcast.target_month.slice(0, 4)} INDICATOR REPORT`);
  yaz(doc, "hedef-ay-kisa", `${ayAdi(ayIso, dil, true).toUpperCase()} ${nowcast.target_month.slice(0, 4)}`);
  yaz(doc, "aciklama-tarih", aciklamaMetni(nowcast.target_month, dil, kisa, true));
  yaz(doc, "aciklama-kutu", aciklamaMetni(nowcast.target_month, dil, kisa, false));
  yaz(doc, "hero-ay", dil === "tr" ? `${ayAdi(ayIso, "tr")} ${ayIso.slice(0, 4)} Aylık Öncü TÜFE` : `${ayAdi(ayIso, "en")} ${ayIso.slice(0, 4)} Flash CPI Nowcast`);

  const sonGercekIx = chart.actual.map((v, i) => [v, i]).filter(([v]) => v !== null).pop();
  const [oncekiDeger, oncekiIx] = sonGercekIx ?? [null, null];
  const delta = orta - (oncekiDeger ?? orta);
  yaz(doc, "nowcast-deger", yuzde(orta, 2, dil));
  const deltaEl = doc.querySelector('[data-alan="nowcast-delta"]');
  if (deltaEl) {
    deltaEl.textContent = delta < 0 ? `▼ ${sayi(delta, 2, dil)} p` : `▲ +${sayi(delta, 2, dil)} p`;
    deltaEl.classList.toggle("text-accent-green", delta < 0);
    deltaEl.classList.toggle("text-accent-red", delta >= 0);
  }
  if (oncekiDeger !== null) {
    const ayK = ayAdi(chart.months[oncekiIx], dil, true);
    yaz(doc, "onceki-gercek", `${ayK} ${dil === "tr" ? "TÜİK" : "TurkStat"}: ${yuzde(oncekiDeger, 2, dil)}`);
  }
  yaz(doc, "yillik-deger", `~${yuzde(nowcast.yillik.point, 1, dil)}`);
  yaz(doc, "yillik-bant", `${dil === "tr" ? "Bant" : "Band"}: ${yuzde(nowcast.yillik.lower, 1, dil)} — ${yuzde(nowcast.yillik.upper, 1, dil)}`);
  yaz(doc, "model-sayisi", String(ok.length));
  yaz(doc, "yayilim", `${yuzde(Math.min(...puanlar), 2, dil)} — ${yuzde(Math.max(...puanlar), 2, dil)}`);

  const cetvel = cetvelPozisyonlari(nowcast);
  yaz(doc, "cetvel-olcek", `${dil === "tr" ? "Ölçek" : "Scale"}: ${yuzde(cetvel.olcekMin, 1, dil)} — ${yuzde(cetvel.olcekMax, 1, dil)}`);
  const span = doc.querySelector('[data-alan="cetvel-span"]');
  if (span) {
    span.style.left = `${cetvel.spanBaslangic}%`;
    span.style.width = `${cetvel.spanGenislik}%`;
  }
  const maxIsaret = doc.querySelector('[data-alan="cetvel-max"]');
  if (maxIsaret) maxIsaret.style.left = `${cetvel.maxPos}%`;
  const pin = doc.querySelector('[data-alan="cetvel-pin"]');
  if (pin) pin.style.left = `${cetvel.pinPos}%`;
  yaz(doc, "cetvel-min-deger", yuzde(cetvel.min, 2, dil));
  yaz(doc, "cetvel-min-model", `(${MODEL[cetvel.minModel]?.[dil] ?? cetvel.minModel})`);
  yaz(doc, "cetvel-medyan-deger", yuzde(cetvel.med, 2, dil));
  yaz(doc, "cetvel-max-deger", yuzde(cetvel.max, 2, dil));
  yaz(doc, "cetvel-max-model", `(${MODEL[cetvel.maxModel]?.[dil] ?? cetvel.maxModel})`);

  yaz(doc, "stat-mae-12", kisa || dil === "en" ? `${sayi(scores.median_mae_12m, 2, dil)} pp` : `${sayi(scores.median_mae_12m, 2, dil)} puan`);
  // Oran alanları JSON'da 0–1 aralığındadır; payda 0 iken export null yazar —
  // null * 100 = 0 sahte sıfır üretir, bu yüzden açık "—" gösterilir.
  const oranYuzde = (v) => (v === null || v === undefined) ? "—" : yuzde(v * 100, 1, dil);
  const oran = scores.yon_isabet_12m?.oran;
  yaz(doc, "stat-yon", oran == null ? "—" : kisa ? oranYuzde(oran) : `${oranYuzde(oran)} (${scores.yon_isabet_12m.dogru}/${scores.yon_isabet_12m.toplam})`);
  yaz(doc, "stat-bant", oranYuzde(scores.bant_icinde_12m));
  const lider = scores.scores.find((s) => s.model === "anket_pka" && s.window === "2019→bugün");
  if (lider) yaz(doc, "lider-mae", sayi(lider.mae, 2, dil));

  const svg = doc.getElementById("tahmin-grafik");
  if (svg) svg.innerHTML = grafikSVG(chart, nowcast, "m24", dil);
  // Grafik dipnotundaki ay iddiası da veriden gelir; HTML'de statik ay kalmaz.
  yaz(doc, "grafik-not", dil === "tr" ? `*${ayAdi(ayIso, "tr")} ayı resmî açıklaması bekleniyor` : `*${ayAdi(ayIso, "en")} official release pending`);

  for (const [ad, seri] of Object.entries(seriler)) {
    const kart = surucuKarti(ad, seri, dil, kisa);
    yaz(doc, `${ad}-deger`, kart.deger);
    const deltaKart = doc.querySelector(`[data-alan="${ad}-delta"]`);
    if (deltaKart && kart.delta) {
      deltaKart.textContent = kart.delta;
      deltaKart.classList.toggle("text-amber-400", kart.yon > 0);
      deltaKart.classList.toggle("text-emerald-400", kart.yon < 0);
    }
    if (kart.ayEtiketi) yaz(doc, `${ad}-ay`, kart.ayEtiketi);
    const spark = doc.querySelector(`[data-alan="${ad}-spark"]`);
    if (spark) spark.setAttribute("points", sparkPuanlari(seri.points));
  }

  const tbody = doc.getElementById("models-tbody");
  if (tbody) {
    const skor = arenaSkorlari(scores);
    for (const satir of [...tbody.children]) {
      const model = satir.getAttribute("data-model");
      const s = skor[model];
      if (!s || s.tum === undefined || s.son24 === undefined) {
        satir.remove();
        continue;
      }
      satir.setAttribute("data-name", MODEL[model]?.[dil] ?? model);
      satir.setAttribute("data-mae-all", String(s.tum));
      satir.setAttribute("data-mae-24", String(s.son24));
      const tumEl = satir.querySelector('[data-alan="mae-all"]');
      const yirmiEl = satir.querySelector('[data-alan="mae-24"]');
      if (tumEl) tumEl.textContent = sayi(s.tum, 2, dil);
      if (yirmiEl) yirmiEl.textContent = sayi(s.son24, 2, dil);
    }
    tabloSirala(doc, 4, true);
  }
}

export async function yukleVeDoldur(doc, getir, dil, kisa) {
  const sonuclar = await Promise.allSettled(ADRESLER.map((yol) => getir(yol)));
  const hatalar = sonuclar
    .map((s, i) => (s.status === "rejected" ? `${ADRESLER[i]} (${s.reason?.message ?? s.reason})` : null))
    .filter(Boolean);
  const bant = doc.getElementById("veri-hatasi");
  if (hatalar.length > 0) {
    if (bant) {
      bant.classList.toggle("hidden", false);
      bant.textContent =
        (dil === "tr" ? "Veri yüklenemedi: " : "Data unavailable: ") +
        hatalar.join(", ") +
        (dil === "tr" ? " — sayılar gerçek veri gelmeden doldurulmaz." : " — numbers stay empty until real data loads.");
    }
    return null;
  }
  const veri = {
    nowcast: sonuclar[0].value,
    scores: sonuclar[1].value,
    chart: sonuclar[2].value,
    seriler: {},
  };
  SERILER.forEach((ad, i) => {
    veri.seriler[ad] = sonuclar[3 + i].value;
  });
  // Bant yalnız doldur() başarıyla bittiğinde gizlenir: 200 OK dönen şeması
  // bozuk JSON doldur'u patlatırsa bant açık kalır, sayfa sessiz '…' kalmaz.
  try {
    doldur(doc, veri, dil, kisa);
  } catch (hata) {
    if (bant) {
      bant.classList.toggle("hidden", false);
      bant.textContent =
        (dil === "tr" ? "Veri şeması bozuk: " : "Data schema invalid: ") +
        String(hata) +
        (dil === "tr" ? " — sayılar gerçek veri gelmeden doldurulmaz." : " — numbers stay empty until real data loads.");
    }
    return null;
  }
  if (bant) bant.classList.toggle("hidden", true);
  return veri;
}
