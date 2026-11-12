// site/src/dogrula.ts — T24 çıkış doğrulama katmanı (Review Focus 2).
// Cevaptaki her sayı bağlam metnindeki sayılarla karşılaştırılır; bağlamda
// olmayan sayı uyarı üretir. Sessiz geçiş yok: worker bu uyarıyı response'un
// "dikkat" alanına yazar; halüsinasyon şüphesi kullanıcıdan gizlenmez.

const UYARI = "cevapta doğrulanamayan sayı var";

// Negatif işaret yalnız önceki karakter rakam değilken işaret sayılır: "2026-11"
// ve "bant 0.92-4.24" gibi yazımlar iki ayrı pozitif sayı olarak okunur,
// hatalı negatif token (-11, -4.24) üretilmez.
const SAYI_KALIBI = /(?<!\d)-?\d+(?:[.,]\d+)?/g;

function sayilar(metin: string): number[] {
  return (metin.match(SAYI_KALIBI) ?? [])
    .map((k) => Number(k.replace(",", ".")))
    .filter((s) => Number.isFinite(s));
}

// Cevaptaki sayıları bağlamla karşılaştırır: her sayı bağlamda bulunmalı.
// Ondalık virgül ("2,58") bağlamın nokta yazımıyla ("2.58") eşleşir.
// `sabitSayilar` şablon sabiti beyaz listesidir ve yalnız o şablonun cevabına
// geçirilir (ör. kesinlik cevabındaki %80); varsayılan boş — global beyaz
// liste yok, yoksa uydurma sayılar sessizce geçer (denetçi bulgusu).
export function dogrula(
  cevap: string,
  baglam: string,
  sabitSayilar: number[] = [],
): { uyari: string | null } {
  const baglamSayilari = new Set(sayilar(baglam));
  const dogrulanamayan = sayilar(cevap).filter(
    (s) => !baglamSayilari.has(s) && !sabitSayilar.includes(s),
  );
  return { uyari: dogrulanamayan.length > 0 ? UYARI : null };
}
