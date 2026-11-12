// site/assets_root/grafik.js — chart.json → SVG üretimi (T26).
// Stitch'teki statik SVG silindi; polyline/polygon/eksenler pencereye göre
// JS ile üretilir. Çizim alanı (X0..X1, Y0..Y1) tasarımın viewBox'ıyla aynıdır.
import { ayAdi, medyan, sayi, yuzde } from "./bicim.js";

const X0 = 110, X1 = 830, Y0 = 30, Y1 = 210;

export function pencereVerisi(chart, anahtar) {
  const aylar = chart.windows[anahtar];
  if (!aylar) throw new Error(`bilinmeyen pencere: ${anahtar}`);
  const indeks = new Map(chart.months.map((m, i) => [m, i]));
  const ix = aylar.map((m) => indeks.get(m));
  if (ix.some((i) => i === undefined)) throw new Error("pencere ayları months içinde yok");
  const al = (dizi) => ix.map((i) => dizi[i]);
  return { aylar, gercek: al(chart.actual), medyan: al(chart.forecast_median), lo: al(chart.band_lo), hi: al(chart.band_hi) };
}

function guzelAdim(aralik) {
  const kuv = Math.pow(10, Math.floor(Math.log10(aralik)));
  for (const m of [1, 2, 2.5, 5, 10]) if (kuv * m >= aralik) return kuv * m;
  return kuv * 10;
}

function metin(x, y, icerik, fill, agirlik = 400) {
  return `<text fill="${fill}" font-family="JetBrains Mono" font-size="10" font-weight="${agirlik}" text-anchor="middle" x="${x.toFixed(1)}" y="${y.toFixed(1)}">${icerik}</text>`;
}

export function grafikSVG(chart, nowcast, anahtar, dil) {
  const p = pencereVerisi(chart, anahtar);
  const pin = medyan(nowcast.forecasts.filter((f) => f.ok && f.point !== null).map((f) => f.point));
  const aylar = [...p.aylar, `${nowcast.target_month}-01`];
  const gercek = [...p.gercek, null];
  const med = [...p.medyan, pin];
  const n = aylar.length;
  const xs = aylar.map((_, i) => (n === 1 ? X0 : X0 + ((X1 - X0) * i) / (n - 1)));

  const tumDegerler = [...p.lo, ...p.hi, ...med, ...gercek.filter((v) => v !== null)];
  const yMin = Math.min(0, ...tumDegerler);
  const yMax = Math.max(...tumDegerler);
  const adim = guzelAdim((yMax - yMin) / 5);
  const y = (v) => Y1 - ((v - yMin) / (yMax - yMin)) * (Y1 - Y0);
  const tikYuzde = (t) => (dil === "tr" ? `%${sayi(t, 1, dil)}` : `${sayi(t, 1, dil)}%`);

  const parcalar = [];
  // Eksen çizgileri + etiketleri (alt çizgi solid, diğerleri tasarımındaki dashed)
  for (let t = Math.ceil(yMin / adim) * adim; t <= yMax + 1e-9; t += adim) {
    const tv = Number(t.toFixed(6));
    const yy = y(tv);
    if (Math.abs(tv - yMin) < 1e-9) {
      parcalar.push(`<line stroke="#3f3f46" stroke-width="1" x1="45" x2="880" y1="${yy}" y2="${yy}"></line>`);
    } else {
      parcalar.push(`<line stroke="#27272a" stroke-dasharray="2 3" stroke-width="1" x1="45" x2="880" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"></line>`);
      parcalar.push(`<text fill="#52525b" font-family="JetBrains Mono" font-size="10" text-anchor="end" x="38" y="${(yy + 4).toFixed(1)}">${tikYuzde(tv)}</text>`);
    }
  }

  // %80 bant poligonu — gerçek band_lo/band_hi'den (pim ayı bandın dışında)
  const ust = p.hi.map((v, i) => `${xs[i].toFixed(1)},${y(v).toFixed(1)}`);
  const alt = p.lo.map((v, i) => `${xs[i].toFixed(1)},${y(v).toFixed(1)}`).reverse();
  parcalar.push(`<polygon fill="#1f242d" fill-opacity="0.5" points="${ust.join(" ")} ${alt.join(" ")}"></polygon>`);

  // Arena medyanı (dashed) + TÜİK gerçek (solid) + noktalar
  parcalar.push(`<polyline fill="none" points="${med.map((v, i) => `${xs[i].toFixed(1)},${y(v).toFixed(1)}`).join(" ")}" stroke="#71717a" stroke-dasharray="4 3" stroke-width="1.5"></polyline>`);
  const dolu = gercek.map((v, i) => [v, i]).filter(([v]) => v !== null);
  parcalar.push(`<polyline fill="none" points="${dolu.map(([v, i]) => `${xs[i].toFixed(1)},${y(v).toFixed(1)}`).join(" ")}" stroke="#f4f4f5" stroke-width="1.75"></polyline>`);
  for (const [v, i] of dolu) {
    parcalar.push(`<circle cx="${xs[i].toFixed(1)}" cy="${y(v).toFixed(1)}" fill="#09090b" r="2.5" stroke="#f4f4f5" stroke-width="1.5"></circle>`);
  }

  // Son açıklanan gerçek (odak) ve pim (hedef ay tahmini)
  const [sonGercek, sonGercekIx] = dolu[dolu.length - 1];
  const sonGercekY = y(sonGercek);
  parcalar.push(`<circle cx="${xs[sonGercekIx].toFixed(1)}" cy="${sonGercekY.toFixed(1)}" fill="#f4f4f5" r="3.5"></circle>`);
  parcalar.push(metin(xs[sonGercekIx], sonGercekY - 12, `${yuzde(sonGercek, 2, dil)} (${ayAdi(aylar[sonGercekIx], dil, dil !== "tr")})`, "#f4f4f5", 600));

  const pinX = xs[n - 1], pinY = y(pin);
  parcalar.push(`<line stroke="#10b981" stroke-dasharray="2 2" stroke-width="1" x1="${pinX.toFixed(1)}" x2="${pinX.toFixed(1)}" y1="${(pinY - 25).toFixed(1)}" y2="${Math.min(pinY + 45, Y1).toFixed(1)}"></line>`);
  parcalar.push(`<circle cx="${pinX.toFixed(1)}" cy="${pinY.toFixed(1)}" fill="#10b981" r="4" stroke="#09090b" stroke-width="1.5"></circle>`);
  parcalar.push(metin(pinX, pinY - 12, `${yuzde(pin, 2, dil)} (${dil === "tr" ? "Tahmin" : "Nowcast"})`, "#10b981", 600));

  // X eksen etiketleri — en fazla 9'uncu her biri; pim ayı "*" ile
  const adimIx = Math.ceil(n / 9);
  const secilen = new Set();
  for (let i = 0; i < n - 1; i += adimIx) secilen.add(i);
  secilen.add(n - 1);
  for (const i of [...secilen].sort((a, b) => a - b)) {
    const yy = aylar[i];
    const etiket = `${ayAdi(yy, dil, true)} '${yy.slice(2, 4)}${i === n - 1 ? "*" : ""}`;
    if (i === n - 1) parcalar.push(metin(xs[i], 228, etiket, "#10b981", 600));
    else if (i === sonGercekIx) parcalar.push(metin(xs[i], 228, etiket, "#f4f4f5", 500));
    else parcalar.push(metin(xs[i], 228, etiket, "#71717a"));
  }
  return parcalar.join("");
}
