// site/assets_root/site.js — üç ekranın veriye bağlanması (T26) giriş modülü.
// Sohbet POST bağlantısı + pencere/tablo etkileşimi + boot burada; veri yazma
// doldur.js'te, hesap yardımcıları kartlar.js ve grafik.js'te, biçim bicim.js'te.
// Boot bloğu yalnız document varken koşar; workerd testi saf fonksiyonları import eder.
import { yukleVeDoldur } from "./doldur.js";
import { grafikSVG } from "./grafik.js";
import { tabloSirala } from "./kartlar.js";

// Test yüzeyi: wire.test.ts bu yardımcıları buradan import eder.
export { ayAdi, medyan, sayi, yuzde } from "./bicim.js";
export { grafikSVG, pencereVerisi } from "./grafik.js";
export { cetvelPozisyonlari, sparkPuanlari, surucuKarti, arenaSkorlari, tabloSirala } from "./kartlar.js";
export { doldur, yukleVeDoldur } from "./doldur.js";

function kacir(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export async function sohbetGonder(getir, soru) {
  // Göreli yol: <base> sayesinde kökte /api/sohbet, /tr-nowcast altında
  // /tr-nowcast/api/sohbet'e çözülür.
  return getir("api/sohbet", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ soru }),
  });
}

export function sohbetYaz(el, yanit) {
  if (!el) return;
  el.classList.toggle("hidden", false);
  if (yanit.hata) {
    el.innerHTML = `<div class="text-accent-red">${kacir(yanit.hata)}</div>`;
    return;
  }
  const dikkat = yanit.dikkat
    ? `<span class="border border-amber-500/40 px-1.5 py-0.5 text-amber-400">dikkat: ${kacir(yanit.dikkat)}</span>`
    : "";
  el.innerHTML =
    `<div class="text-text-secondary whitespace-pre-wrap leading-relaxed">${kacir(yanit.cevap)}</div>` +
    `<div class="mt-1 flex items-center gap-2 text-[10px]">` +
    `<span class="border border-border-hairline px-1.5 py-0.5 text-text-muted">kaynak: ${kacir(yanit.kaynak ?? "?")}</span>${dikkat}</div>`;
}

if (typeof document !== "undefined") {
  const doc = document;
  const dil = doc.documentElement.lang === "tr" ? "tr" : "en";
  const kisa = doc.documentElement.getAttribute("data-kisa") === "1";
  const getir = async (yol, secenek) => {
    const r = await fetch(yol, secenek);
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  };

  let pencere = "m24";
  let veri = null;
  const grafikCiz = () => {
    const svg = doc.getElementById("tahmin-grafik");
    if (svg && veri) svg.innerHTML = grafikSVG(veri.chart, veri.nowcast, pencere, dil);
  };

  window.setActiveFilter = (btn) => {
    for (const b of btn.parentElement.querySelectorAll("button")) {
      b.className = "px-2 py-0.5 text-text-dim hover:text-text-secondary transition-colors";
    }
    btn.className = "px-2 py-0.5 bg-zinc-800 text-text-primary font-medium border-x border-border-hairline transition-colors";
  };

  let siralama = { kolon: 4, artan: true };
  window.sortTable = (kolon) => {
    const artan = siralama.kolon === kolon ? !siralama.artan : true;
    siralama = { kolon, artan };
    tabloSirala(doc, kolon, artan);
    doc.querySelectorAll("#models-table thead th").forEach((th, idx) => {
      const icon = th.querySelector(".sort-icon");
      if (!icon) return;
      if (idx === kolon) {
        icon.textContent = artan ? "↓" : "↑";
        icon.className = "sort-icon text-accent-green font-bold";
        th.classList.add("bg-zinc-900/60", "text-text-primary");
      } else {
        icon.textContent = "↕";
        icon.className = "sort-icon text-[10px] text-text-dim";
        th.classList.remove("bg-zinc-900/60", "text-text-primary");
      }
    });
  };

  const grup = doc.getElementById("chart-filter-group");
  if (grup) {
    for (const b of grup.querySelectorAll("button")) {
      b.addEventListener("click", () => {
        pencere = b.getAttribute("data-pencere") ?? "m24";
        window.setActiveFilter(b);
        grafikCiz();
      });
    }
  }

  const girdi = doc.getElementById("sohbet-girdi");
  const dugme = doc.getElementById("sohbet-gonder");
  const sonuc = doc.getElementById("sohbet-sonuc");
  const gonder = async () => {
    if (!girdi || !sonuc || !girdi.value.trim()) return;
    sonuc.classList.toggle("hidden", false);
    sonuc.textContent = "…";
    try {
      sohbetYaz(sonuc, await sohbetGonder(getir, girdi.value.trim()));
    } catch {
      sohbetYaz(sonuc, { hata: dil === "tr" ? "bağlantı kurulamadı" : "connection failed" });
    }
  };
  dugme?.addEventListener("click", gonder);
  girdi?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") gonder();
  });
  for (const c of doc.querySelectorAll('[data-alan="sohbet-ornek"]')) {
    c.addEventListener("click", () => {
      if (girdi) girdi.value = c.textContent.trim();
    });
  }

  yukleVeDoldur(doc, getir, dil, kisa)
    .then((yuklenen) => {
      veri = yuklenen;
      grafikCiz();
    })
    .catch((hata) => {
      // Son savunma hattı: beklenmeyen her reddedilme bantı açar, sessiz '…' kalmaz.
      const bant = doc.getElementById("veri-hatasi");
      if (bant) {
        bant.classList.toggle("hidden", false);
        bant.textContent =
          (dil === "tr" ? "Veri bağlanamadı: " : "Data binding failed: ") +
          String(hata) +
          (dil === "tr" ? " — sayılar gerçek veri gelmeden doldurulmaz." : " — numbers stay empty until real data loads.");
      }
    });
}
