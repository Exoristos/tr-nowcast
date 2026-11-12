// site/assets_root/kartlar.js — cetvel, sürücü kartı, arena ve tablo yardımcıları (T26).
// Saf fonksiyonlar: DOM'a dokunmaz, workerd testinde import edilebilir.
import { ayAdi, medyan, sayi, yuzde } from "./bicim.js";

export const MODEL = {
  naive: { tr: "Naive", en: "Naive" },
  seasonal_naive: { tr: "Seasonal-naive", en: "Seasonal-naive" },
  arima: { tr: "ARIMA(1,0,0)", en: "ARIMA(1,0,0)" },
  ets: { tr: "ETS", en: "ETS" },
  chronos2_uni: { tr: "Chronos-2", en: "Chronos-2" },
  timesfm3_mv: { tr: "TimesFM 3.0", en: "TimesFM 3.0" },
  bridge: { tr: "Bridge / MIDAS-lite", en: "Bridge / MIDAS-lite" },
  anket_pka: { tr: "TCMB beklenti anketi", en: "CBRT Survey" },
};

export const SERILER = ["usd_aylik", "brent_aylik", "fao_aylik", "anket_pka", "tufe_aylik"];

const SERI_BICIM = {
  usd_aylik: (v, d) => sayi(v, 2, d),
  brent_aylik: (v, d) => `${sayi(v, 1, d)} $`,
  fao_aylik: (v, d) => sayi(v, 1, d),
  anket_pka: (v, d) => yuzde(v, 2, d),
  tufe_aylik: (v, d) => yuzde(v, 2, d),
};

export function sonrakiAyIso(hedef) {
  const yil = Number(hedef.slice(0, 4));
  const ay = Number(hedef.slice(5, 7));
  return ay === 12 ? `${yil + 1}-01-01` : `${yil}-${String(ay + 1).padStart(2, "0")}-01`;
}

export function cetvelPozisyonlari(nowcast) {
  const puanlar = nowcast.forecasts.filter((f) => f.ok && f.point !== null).map((f) => f.point);
  const min = Math.min(...puanlar);
  const max = Math.max(...puanlar);
  const med = medyan(puanlar);
  const olcekMin = Math.max(0, Math.floor((min - 0.5) * 2) / 2);
  const olcekMax = Math.ceil((max + 0.5) * 2) / 2;
  const pos = (v) => ((v - olcekMin) / (olcekMax - olcekMin)) * 100;
  const minModel = nowcast.forecasts.find((f) => f.point === min)?.model ?? "";
  const maxModel = nowcast.forecasts.find((f) => f.point === max)?.model ?? "";
  return { min, med, max, minModel, maxModel, olcekMin, olcekMax, spanBaslangic: pos(min), spanGenislik: pos(max) - pos(min), pinPos: pos(med), maxPos: pos(max) };
}

export function sparkPuanlari(noktalar, adet = 12) {
  const dilim = noktalar.slice(-adet).map(([, v]) => Number(v));
  const vMin = Math.min(...dilim);
  const vMax = Math.max(...dilim);
  const yay = vMax - vMin;
  const n = dilim.length;
  return dilim
    .map((v, i) => {
      const x = n === 1 ? 0 : (100 * i) / (n - 1);
      const yOran = yay === 0 ? 0.5 : (v - vMin) / yay;
      return `${x.toFixed(1)},${(22 - yOran * 20).toFixed(1)}`;
    })
    .join(" ");
}

export function surucuKarti(ad, seri, dil, kisa) {
  const p = seri.points;
  const [sonAy, son] = p[p.length - 1];
  const onceki = p.length > 1 ? p[p.length - 2][1] : null;
  const isaret = (v) => (v >= 0 ? "+" : "-");
  let delta = null;
  let yon = 0;
  if (ad !== "tufe_aylik" && onceki !== null && onceki !== 0) {
    if (ad === "anket_pka") {
      const deg = son - onceki;
      delta = kisa ? `${isaret(deg)}${sayi(Math.abs(deg), 2, dil)}pp` : `${isaret(deg)}${sayi(Math.abs(deg), 2, dil)} p M/M`;
      yon = Math.sign(deg);
    } else {
      const oran = ((son - onceki) / Math.abs(onceki)) * 100;
      delta = kisa ? `${isaret(oran)}${sayi(Math.abs(oran), 1, dil)}%` : `${isaret(oran)}${sayi(Math.abs(oran), 1, dil)}% M/M`;
      yon = Math.sign(oran);
    }
  }
  const ayT = ayAdi(sonAy, dil);
  const ayK = ayAdi(sonAy, dil, true);
  const yil = sonAy.slice(0, 4);
  let ayEtiketi = null;
  if (ad === "usd_aylik") ayEtiketi = dil === "tr" ? `${ayT} Ortalaması` : `${kisa ? ayK : ayT} Avg`;
  else if (ad === "fao_aylik") ayEtiketi = dil === "tr" ? `FAO Gıda Endeksi, ${ayT}` : kisa ? `${ayK} Index` : `FAO Food Index, ${ayT}`;
  else if (ad === "anket_pka") ayEtiketi = dil === "tr" ? `Piyasa Katılımcıları, ${ayT}` : kisa ? `${ayK} Surv` : `Market Participants, ${ayT}`;
  else if (ad === "tufe_aylik") ayEtiketi = dil === "tr" ? `Aylık TÜİK, ${ayT} ${yil}` : kisa ? `TurkStat ${ayK} '${yil.slice(2)}` : `Monthly TurkStat, ${ayT} ${yil}`;
  const deger = SERI_BICIM[ad](son, dil);
  return { deger, delta, yon, ayEtiketi };
}

export function arenaSkorlari(scores) {
  const harita = {};
  for (const s of scores.scores) {
    const h = (harita[s.model] ??= {});
    if (s.window === "2019→bugün") h.tum = s.mae;
    else if (s.window === "son 24 ay") h.son24 = s.mae;
  }
  return harita;
}

export function tabloSirala(doc, kolon, artan) {
  const tbody = doc.getElementById("models-tbody");
  if (!tbody) return;
  const anahtar = kolon === 1 ? "data-name" : kolon === 3 ? "data-mae-all" : "data-mae-24";
  const satirlar = [...tbody.children].sort((a, b) => {
    const va = a.getAttribute(anahtar) ?? "";
    const vb = b.getAttribute(anahtar) ?? "";
    const k = kolon === 1 ? va.localeCompare(vb, "tr") : Number(va) - Number(vb);
    return artan ? k : -k;
  });
  satirlar.forEach((satir, i) => {
    const hucre = satir.querySelector(".row-idx");
    if (hucre) hucre.textContent = String(i + 1).padStart(2, "0");
    tbody.appendChild(satir);
  });
}
