// site/assets_root/bicim.js — sayı/ay biçimlendirme (T26).
// Intl bilinçli kullanılmaz: workerd test ortamı tam yerel desteği vermez;
// biçim Stitch tasarımındaki gösterime (tr: %2,18 / en: 2.18%) sabitlenir.

export const AYLAR = {
  tr: ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

export function sayi(n, hane = 2, dil = "tr") {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(hane).replace(".", dil === "tr" ? "," : ".");
}

export function yuzde(n, hane = 2, dil = "tr") {
  return dil === "tr" ? `%${sayi(n, hane, dil)}` : `${sayi(n, hane, dil)}%`;
}

export function ayAdi(iso, dil = "tr", kisa = false) {
  const ay = Number(String(iso).slice(5, 7)) - 1;
  const ad = AYLAR[dil][ay] ?? "—";
  return kisa ? ad.slice(0, 3) : ad;
}

export function medyan(sirali) {
  if (!Array.isArray(sirali) || sirali.length === 0) return NaN;
  const s = [...sirali].sort((a, b) => a - b);
  const orta = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[orta] : (s[orta - 1] + s[orta]) / 2;
}
