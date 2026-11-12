// site/src/prompt.ts — prompt derleyici, konu sınıflandırıcılar ve sabit red şablonları.
// Bağlam YALNIZ data/site/*.json içeriğinden derlenir; başka kaynak (web, model
// bilgisi) giremez (plan Global Constraint). Bu dosya saf fonksiyonlardan oluşur; IO yok.

export interface NowcastTahmin {
  model: string;
  point: number | null;
  lower: number | null;
  upper: number | null;
  ok: boolean;
  error: string | null;
}

export interface YillikTahmin {
  point: number;
  lower: number;
  upper: number;
  temel: string;
}

export interface NowcastVeri {
  generated_at: string;
  cutoff_date: string;
  target_month: string;
  forecasts: NowcastTahmin[];
  yillik: YillikTahmin | null;
}

export interface SkorKaydi {
  model: string;
  window: string;
  mae: number;
  rmse: number;
  n: number;
  n_failed: number;
  hit80_rate: number;
}

export interface SkorlarVeri {
  generated_at: string;
  windows: string[];
  scores: SkorKaydi[];
}

export interface MetaVeri {
  generated_at: string;
  registry: Record<string, Record<string, unknown>>;
}

// data/site/series/*.json şeması (README): points ay-başı ISO tarih + değer.
export interface SeriVeri {
  series: string;
  unit: string;
  points: [string, number][];
}

export interface SiteVeri {
  nowcast: NowcastVeri;
  scores: SkorlarVeri;
  meta: MetaVeri;
  seriler?: SeriVeri[];
}

export type Kaynak = "veri" | "red" | "tavsiye_redi" | "yapim";

// Sabit şablonlar — kalkanlar LLM'e bırakılmaz, kod seviyesinde döner (Review Focus 3-4).
export const TAVSIYE_REDI =
  "Yatırım tavsiyesi veremem. Bu site TÜFE nowcast tahminlerini gösterir; " +
  "alım-satım, portföy veya yatırım kararı önerisi yapmam. Bu tür kararlar için " +
  "lisanslı bir finansal danışmana başvurun.";

export const VERI_DISI_REDI =
  "Bu sorunun cevabı elimdeki veride yok. Yalnızca site verisindeki TÜFE aylık " +
  "nowcast tahminleri, model karşılaştırma skorları, seri değerleri ve veri " +
  "kaynakları hakkında konuşabilirim. Verimde olmayan konularda (büyüme, siyaset, " +
  "gelecek döviz kuru vb.) 'verimde yok' demem gerekir.";

// Yapım bilgisi: "kim yaptı?" tipi sorular bağlamda üretici bilgisi olmadığından
// LLM'e bırakılamaz (LLM 'verimde yok' diyecektir); kod seviyesinde sabit cevap.
// Sayısızdır — çıkış doğrulaması temiz geçer.
export const YAPIM_BILGISI =
  "TR-Nowcast projesi Enis Erdoğan tarafından geliştirildi — Marmara Üniversitesi " +
  "İstatistik öğrencisi. Veri hattı, modeller ve arenadaki Bridge / MIDAS-lite bu " +
  "projede sıfırdan yazıldı; kod github.com/Exoristos/tr-nowcast adresinde açık. " +
  "Bu sohbet kutusu ise site verisini sorgulayan bir arayüzdür.";

// Yatırım kalkanı bilinçli olarak geniş: "altın almalı mıyım", "satalım mı" gibi
// kalıplar da LLM'e hiç gitmez (Review Focus 4).
const YATIRIM_KELIMELERI = [
  "yatırım", "yatirim", "alayım", "alayim", "alsam", "almalı", "almali",
  "satalım", "satalim", "satayım", "satayim", "satsam", "portföy", "portfoy",
  "altın", "altin", "borsa", "hisse", "kripto", "bitcoin",
];
const KESINLIK_KELIMELERI = [
  "kesin mi", "kesinlik", "garanti", "emin mi", "güvenilir mi", "guvenilir",
  "hata payı", "hata payi",
];
// Mock modda "veri sorusu" sayılacak konular — bağlamda olan konularla sınırlı
// (nowcast + skorlar + seriler). "Yarın dolar kaç TL" gibi gelecek-değer soruları
// bağlamda yoktur: gelecekSorulariMi bunları red'e düşürür.
const VERI_KONU_KELIMELERI = [
  "enflasyon", "tüfe", "tufe", "nowcast", "tahmin", "tahmini", "model",
  "arima", "arıma", "ets", "chronos", "timesfm", "bridge", "naive", "yıllık",
  "yillik", "mae", "bant", "skor", "isabet", "dolar", "usd", "kur", "brent",
  "petrol", "gıda", "gida", "fao", "anket",
];
const GELECEK_KELIMELERI = ["yarın", "yarin"];

// Yalnız deyim düzeyi kalıplar: tek başına "kim" veya "kimin" geniş olur
// ("TCMB başkanı kim?", "kimin tahmini iyi?" yanlış pozitif olur).
const YAPIM_KELIMELERI = [
  "kim yaptı", "kim yapmış", "kim geliştirdi", "kim geliştiriyor", "kim yazdı",
  "kim tasarladı", "kim kurdu", "kim tarafından", "geliştiren",
  "who made", "who developed", "who created", "who built", "who wrote",
  "developer", "author",
];

function norm(metin: string): string {
  return metin.toLocaleLowerCase("tr");
}

export function tavsiyeSorulariMi(soru: string): boolean {
  const kucuk = norm(soru);
  return YATIRIM_KELIMELERI.some((k) => kucuk.includes(k));
}

export function kesinlikSorulariMi(soru: string): boolean {
  const kucuk = norm(soru);
  return KESINLIK_KELIMELERI.some((k) => kucuk.includes(k));
}

export function veriKonuMu(soru: string): boolean {
  const kucuk = norm(soru);
  return VERI_KONU_KELIMELERI.some((k) => kucuk.includes(k));
}

export function gelecekSorulariMi(soru: string): boolean {
  const kucuk = norm(soru);
  return GELECEK_KELIMELERI.some((k) => kucuk.includes(k));
}

export function yapimSorulariMi(soru: string): boolean {
  const kucuk = norm(soru);
  return YAPIM_KELIMELERI.some((k) => kucuk.includes(k));
}

function fmt(sayi: number): string {
  return sayi.toFixed(2);
}

// Review Focus 3: "kesin mi?" sorusuna şablon cevap — bantlar ve MAE'lerle
// belirsizliği anlatır; kesinlik iddiası dilinde konuşmaz. Tüm modeller başarısızsa
// da Infinity gibi çöp sayı üretmez.
// %80 bandı şemanın sabitidir (README nowcast/skor tabloları); skor tablosu
// boşken bağlam metninde geçmeyebilir. Beyaz liste YALNIZ bu şablonun
// ürettiği cevap için dogrula'ya geçirilir (dogrula.ts — global beyaz liste yok).
export const KESINLIK_SABIT_SAYILARI: number[] = [80];
export function kesinlikCevabi(veri: SiteVeri): string {
  const tahminler = veri.nowcast.forecasts.filter(
    (t) => t.ok && t.point !== null && t.lower !== null && t.upper !== null,
  );
  const noktalar = tahminler.flatMap((t) => [t.point as number]);
  const maeler = veri.scores.scores.map((k) => k.mae);
  const bolumler: string[] = [];
  if (noktalar.length > 0) {
    bolumler.push(
      `Bu tahminler kesin değildir. ${veri.nowcast.target_month} ayı için modeller ` +
        `aylık ${fmt(Math.min(...noktalar))}%–${fmt(Math.max(...noktalar))}% arasında ` +
        `farklı değerler veriyor ve her tahmin %80 güven bandıyla geliyor.`,
    );
  } else {
    bolumler.push(
      "Bu tahminler kesin değildir; şu an geçerli bir nokta tahmin yok (modeller " +
        "başarısız), bu yüzden kesinlik de iddia edilemez. Tahminler her zaman " +
        "%80 güven bandı ve geçmiş MAE hatasıyla anlatılır.",
    );
  }
  if (veri.nowcast.yillik !== null) {
    const y = veri.nowcast.yillik;
    bolumler.push(
      `Yıllık türetme ${fmt(y.point)}% (bant ${fmt(y.lower)}–${fmt(y.upper)}; temel: ${y.temel}).`,
    );
  }
  if (maeler.length > 0) {
    bolumler.push(
      `Geçmiş performans: modellerin MAE'leri ${fmt(Math.min(...maeler))}–` +
        `${fmt(Math.max(...maeler))} puan arasında değişiyor — tipik sapma bu kadar.`,
    );
  }
  bolumler.push("Kesin bir sayı iddia edemem; yalnız aralık ve hata payı verebilirim.");
  return bolumler.join(" ");
}

function tahminSatiri(t: NowcastTahmin): string {
  if (!t.ok || t.point === null || t.lower === null || t.upper === null) {
    return `- ${t.model}: tahmin yok (başarısız)`;
  }
  return `- ${t.model}: ${fmt(t.point)}% (bant ${fmt(t.lower)}–${fmt(t.upper)})`;
}

function nowcastBloku(n: NowcastVeri): string {
  const satirlar = n.forecasts.map(tahminSatiri).join("\n");
  const yillik =
    n.yillik === null
      ? "Yıllık türetme: yok"
      : `Yıllık türetme: ${fmt(n.yillik.point)}% ` +
        `(bant ${fmt(n.yillik.lower)}–${fmt(n.yillik.upper)}; temel: ${n.yillik.temel})`;
  return `Hedef ay: ${n.target_month} (veri kesiti: ${n.cutoff_date})\n` +
    `Aylık tahminler (aylık %):\n${satirlar}\n${yillik}`;
}

function skorBloku(s: SkorlarVeri): string {
  const satirlar = s.scores
    .map(
      (k) =>
        `- ${k.model} [${k.window}]: MAE ${fmt(k.mae)}, RMSE ${fmt(k.rmse)}, ` +
        `n=${k.n}, %80 isabet ${(k.hit80_rate * 100).toFixed(0)}%`,
    )
    .join("\n");
  return `Model karşılaştırma skorları (gerçek aylara karşı):\n${satirlar}`;
}

function seriBloku(seriler: SeriVeri[]): string {
  const satirlar = seriler
    .map((s) => {
      const son12 = s.points.slice(-12);
      const degerler = son12
        .map(([tarih, deger]) => `${tarih.slice(0, 7)}:${deger.toFixed(2)}`)
        .join(", ");
      return `- ${s.series} (${s.unit}), son 12 ay: ${degerler || "değer yok"}`;
    })
    .join("\n");
  return `Seri değerleri (aylık seriler):\n${satirlar}`;
}

function metaBloku(m: MetaVeri): string {
  const satirlar = Object.entries(m.registry)
    .map(([ad, kayit]) => `- ${ad}: kaynak ${String(kayit.source ?? "bilinmiyor")}`)
    .join("\n");
  return `Veri kaynakları:\n${satirlar}`;
}

// Prompt derleyici: soru + yalnız site verisinden derlenen sıkışık bağlam.
// Architecture'a göre bağlam: nowcast özeti + arena tablosu + son 12 ay seri değerleri.
// `baglam` döndürülür ki çıkış doğrulaması (dogrula) yalnız bu bölümle
// yapılabilsin; kullanici metnindeki SORU satırı kullanıcı kontrolündedir ve
// oradaki sayılar doğrulanmış sayılamaz (denetçi bulgusu, RF2).
export function derle(
  soru: string,
  veri: SiteVeri,
): { system: string; kullanici: string; baglam: string } {
  const system = [
    "Sen TR-Nowcast sitesinin veri asistanısın. Şu kurallara harfiyen uy:",
    "1. Yalnızca kullanıcının mesajındaki BAĞLAM bölümündeki veriyi kullan; " +
      "bağlamda olmayan hiçbir sayıyı, olayı veya bilgiyi söyleme.",
    "2. Bağlamda olmayan bir şey sorulursa kısaca 'bu bilgi verimde yok' de ve " +
      "konuyu verideki konulara yönlendir.",
    "3. 'Tahmin' ile 'gerçek' ayrımını koru: nowcast bir tahmindir, %80 bandıyla " +
      "ve geçmiş MAE hatasıyla anlatılır; asla kesinlik iddiasında bulunma.",
    "4. Yatırım, portföy veya alım-satım tavsiyesi istenirse vermeyi reddet.",
    "5. Sorunun dilinde cevap ver (Türkçe soruya Türkçe), tarafsız ve kısa ol.",
  ].join("\n");
  const seriler =
    veri.seriler === undefined ? "" : `\n\n${seriBloku(veri.seriler)}`;
  const baglam =
    `${nowcastBloku(veri.nowcast)}\n\n${skorBloku(veri.scores)}${seriler}` +
    `\n\n${metaBloku(veri.meta)}`;
  const kullanici =
    `SORU: ${soru}\n\n` +
    `BAĞLAM (yalnız site verisi, data/site JSON'larından derlendi):\n${baglam}`;
  return { system, kullanici, baglam };
}
