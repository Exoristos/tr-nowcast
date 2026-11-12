// site/src/worker.ts — assets servis + mobil UA yönlendirme + POST /api/sohbet.
// MOCK kod yolu yalnız test ortamı içindir; deploy edilen worker'da MOCK var'ı
// tanımlı değildir, sohbet canlı LLM'e gider (plan T27: MOCK kaldırıldı).
import { dogrula } from "./dogrula";
import {
  derle,
  gelecekSorulariMi,
  kesinlikCevabi,
  kesinlikSorulariMi,
  tavsiyeSorulariMi,
  veriKonuMu,
  yapimSorulariMi,
  KESINLIK_SABIT_SAYILARI,
  TAVSIYE_REDI,
  VERI_DISI_REDI,
  YAPIM_BILGISI,
  type Kaynak,
  type SiteVeri,
} from "./prompt";

export interface Env {
  AI: Ai;
  ASSETS: Fetcher;
  /** "1" ise LLM çağrısı yapılmaz; sabit yanıt döner (CI/yerel test güvencesi). */
  MOCK?: string;
}

export interface SohbetYanit {
  cevap: string;
  kaynak: Kaynak;
  dikkat: string | null;
}

const SOHBET_YOLU = "/api/sohbet";
const AI_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast";

// exoristos.dev/tr-nowcast altındaki istekler aynı worker'ı kullanır: önek burada
// soyulur, geri kalan mantık kök yollarla çalışır. Önek zorunlu değildir —
// öneksiz (workers.dev) istek birebir eski davranışı sürdürür.
const ONEK = "/tr-nowcast";

function onekSoyu(pathname: string): { yol: string; onek: string } {
  if (pathname === ONEK) return { yol: "/", onek: ONEK };
  if (pathname.startsWith(`${ONEK}/`)) return { yol: pathname.slice(ONEK.length), onek: ONEK };
  return { yol: pathname, onek: "" };
}

// Mobil yönlendirme yalnız TR masaüstü sayfasından (/ ve /index.html) yapılır
// (plan T27). /m/ yol koşula uymadığı için mobil UA'da kendine 302 atmaz —
// döngü oluşmaz (Review Focus 4). /en/ ve varlıklar da yönlendirilmez. Hedef
// önekle yazılır: kökte /m/, önek altında /tr-nowcast/m/.
const MOBIL_UA = /Android|iPhone|iPad|iPod|IEMobile|Mobile/i;

function mobilYonlendirme(yol: string, onek: string, url: URL, request: Request): Response | null {
  if (request.method !== "GET" && request.method !== "HEAD") return null;
  if (yol !== "/" && yol !== "/index.html") return null;
  const ua = request.headers.get("user-agent") ?? "";
  if (!MOBIL_UA.test(ua)) return null;
  const hedef = new URL(`${onek}/m/`, url.origin);
  hedef.search = url.search;
  return new Response(null, {
    status: 302,
    headers: { location: hedef.toString() },
  });
}

// Önekli girişte uzantısız ve slash'sız yol bir dizindir (/tr-nowcast,
// /tr-nowcast/en): sayfanın göreli URL tabanı ancak trailing slash ile doğru
// kurulur; ASSETS'in kendi dizin yönlendirmesi de önek dışına mutlak yol
// yazabilir. Bu yüzden normalleştirmeyi worker üstlenir; öneksiz isteklerde
// ASSETS'e bırakılır (mevcut davranış değişmez).
function dizinYonlendir(url: URL, onek: string): Response | null {
  if (onek === "") return null;
  const yol = url.pathname;
  const son = yol.slice(yol.lastIndexOf("/") + 1);
  if (yol.endsWith("/") || son.includes(".")) return null;
  const hedef = new URL(`${onek}${yol.slice(ONEK.length)}/`, url.origin);
  hedef.search = url.search;
  return new Response(null, { status: 308, headers: { location: hedef.toString() } });
}

// README'de belgelenmiş site seri seti; ASSETS binding'inin dizin listeleme API'si
// olmadığından dosya adları sabit tutulur. Eksik dosya normal iş akışıdır (atlanır).
const SERI_DOSYALARI = ["tufe_aylik", "usd_aylik", "brent_aylik", "fao_aylik", "anket_pka"];

function jsonYanit(govde: SohbetYanit | { hata: string }, durum: number): Response {
  return new Response(JSON.stringify(govde), {
    status: durum,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// Assets sınırında minimal şekil doğrulaması: şema dışı veri 503 ile düşer,
// handler'ın derinlerine şema dışı nesne sızmaz.
function sekilHatalari(veri: SiteVeri): string[] {
  const hatalar: string[] = [];
  const n = veri.nowcast;
  if (!n || typeof n.target_month !== "string" || !Array.isArray(n.forecasts)) {
    hatalar.push("nowcast: target_month/forecasts eksik");
  }
  if (!veri.scores || !Array.isArray(veri.scores.scores)) {
    hatalar.push("scores: scores dizisi eksik");
  }
  if (!veri.meta || typeof veri.meta.registry !== "object" || veri.meta.registry === null) {
    hatalar.push("meta: registry eksik");
  }
  if (veri.seriler !== undefined) {
    if (!Array.isArray(veri.seriler)) {
      hatalar.push("seriler: dizi olmalı");
    } else {
      veri.seriler.forEach((s, i) => {
        if (!s || typeof s.series !== "string" || !Array.isArray(s.points)) {
          hatalar.push(`seriler[${i}]: series/points eksik`);
        }
      });
    }
  }
  return hatalar;
}

// Site verisi deploy edilen assets'ten okunur — prompt'a giren tek kaynak bu.
async function veriYukle(env: Env, temel: string): Promise<SiteVeri> {
  const [nowcast, scores, meta] = await Promise.all(
    ["/nowcast.json", "/scores.json", "/meta.json"].map(async (yol) => {
      const yanit = await env.ASSETS.fetch(new Request(new URL(yol, temel).toString()));
      if (!yanit.ok) throw new Error(`assets verisi okunamadı: ${yol} (${yanit.status})`);
      return yanit.json() as Promise<unknown>;
    }),
  );
  const seriHammaddeleri = await Promise.all(
    SERI_DOSYALARI.map(async (ad) => {
      const yanit = await env.ASSETS.fetch(
        new Request(new URL(`/series/${ad}.json`, temel).toString()),
      );
      if (!yanit.ok) return null; // eksik seri normal: atlanır
      return yanit.json() as Promise<unknown>;
    }),
  );
  const seriler = seriHammaddeleri.filter((s) => s !== null);
  // Veri kendi export aracımızın çıktısı; yine de sınırda şekil doğrulanır.
  const veri = { nowcast, scores, meta, seriler } as SiteVeri;
  const hatalar = sekilHatalari(veri);
  if (hatalar.length > 0) {
    throw new Error(`site verisi şema dışı: ${hatalar.join("; ")}`);
  }
  return veri;
}

export default {
  async fetch(request, env, _ctx): Promise<Response> {
    const url = new URL(request.url);
    const { yol, onek } = onekSoyu(url.pathname);
    const yonlendirme = mobilYonlendirme(yol, onek, url, request);
    if (yonlendirme) return yonlendirme;
    if (yol !== SOHBET_YOLU) {
      const dizin = dizinYonlendir(url, onek);
      if (dizin) return dizin;
      if (onek === "") return env.ASSETS.fetch(request);
      // Önekli istek ASSETS'e soyulmuş yolla gider; sorgu dizisi korunur.
      const soyulmus = new URL(url.toString());
      soyulmus.pathname = yol;
      return env.ASSETS.fetch(new Request(soyulmus, request));
    }

    if (request.method !== "POST") {
      return jsonYanit({ hata: "yalnızca POST kabul edilir" }, 405);
    }

    let soru: unknown;
    try {
      const govde = (await request.json()) as { soru?: unknown };
      soru = govde.soru;
    } catch {
      return jsonYanit({ hata: "gövde geçerli JSON değil" }, 400);
    }
    if (typeof soru !== "string" || soru.trim().length === 0) {
      return jsonYanit({ hata: "'soru' alanı boş olmayan bir metin olmalı" }, 400);
    }

    // Beklenmedik her hata (veri yüklenememesi, bağlam derleme sorunları) JSON
    // gövdesiyle döner; workerd çökmesine izin verilmez.
    try {
      let veri: SiteVeri;
      try {
        veri = await veriYukle(env, url.origin);
      } catch (hata) {
        return jsonYanit({ hata: `site verisi yüklenemedi: ${String(hata)}` }, 503);
      }

      // Kod seviyesi kalkanlar — LLM'e bırakılmaz (Review Focus 3 ve 4).
      if (tavsiyeSorulariMi(soru)) {
        return jsonYanit({ cevap: TAVSIYE_REDI, kaynak: "tavsiye_redi", dikkat: null }, 200);
      }
      if (kesinlikSorulariMi(soru)) {
        const cevap = kesinlikCevabi(veri);
        // Şablon sabiti (%80) yalnız bu kod-üretimi cevap için beyaz listelenir.
        const { uyari } = dogrula(
          cevap,
          derle(soru, veri).baglam,
          KESINLIK_SABIT_SAYILARI,
        );
        return jsonYanit({ cevap, kaynak: "veri", dikkat: uyari }, 200);
      }
      // Yapım sorusu bağlamda olmadığından LLM'e gitmez; sabit kendini tanıtma.
      if (yapimSorulariMi(soru)) {
        return jsonYanit({ cevap: YAPIM_BILGISI, kaynak: "yapim", dikkat: null }, 200);
      }

      // MOCK=1: LLM çağrısı hiç yapılmaz (plan Global Constraint). Gelecek-değer
      // soruları (ör. "yarın dolar kaç TL") bağlamda yoktur → red.
      if (env.MOCK === "1") {
        if (veriKonuMu(soru) && !gelecekSorulariMi(soru)) {
          const derlenen = derle(soru, veri);
          const cevap =
            `MOCK modu — LLM çağrısı yapılmadı. Derlenen bağlam:\n\n` +
            `${derlenen.kullanici}`;
          // Cevap kullanici metninin birebir yansıması; kendisiyle doğrulanır.
          const { uyari } = dogrula(cevap, derlenen.kullanici);
          return jsonYanit({ cevap, kaynak: "veri", dikkat: uyari }, 200);
        }
        return jsonYanit({ cevap: VERI_DISI_REDI, kaynak: "red", dikkat: null }, 200);
      }

      const { system, kullanici, baglam } = derle(soru, veri);
      try {
        const sonuc = (await env.AI.run(AI_MODEL, {
          messages: [
            { role: "system", content: system },
            { role: "user", content: kullanici },
          ],
        })) as { response?: unknown };
        const cevap = typeof sonuc.response === "string" ? sonuc.response.trim() : "";
        if (cevap.length === 0) return jsonYanit({ hata: "LLM boş yanıt döndürdü" }, 502);
        // Çıkış doğrulaması (Review Focus 2): cevaptaki sayılar YALNIZ BAĞLAM
        // bölümüyle karşılaştırılır; SORU satırı kullanıcı kontrolünde olduğundan
        // oradaki sayılar doğrulanmış sayılamaz. Doğrulanamayan sayı "dikkat"
        // ile işaretlenir — sessiz geçilmez.
        const { uyari } = dogrula(cevap, baglam);
        return jsonYanit({ cevap, kaynak: "veri", dikkat: uyari }, 200);
      } catch (hata) {
        return jsonYanit({ hata: `LLM çağrısı başarısız: ${String(hata)}` }, 502);
      }
    } catch (hata) {
      return jsonYanit({ hata: `yanıt üretilemedi: ${String(hata)}` }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
