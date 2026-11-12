// site/tests/ortam.ts — worker testleri için paylaşılan mock ortam (binding + UA).
// MOCK=1 garantisi: test ortamındaki AI binding çağrılırsa test patlar — gerçek LLM'e çıkılmaz.
import type { Env } from "../src/worker";
import worker from "../src/worker";
import { veri } from "./veri";

export function mockEnv(
  opsiyon: {
    mock?: boolean;
    seriYok?: boolean;
    kirikVeri?: boolean;
    /** Verilirse ASSETS'e giden her yol bu diziye yazılır (önek soyma testleri). */
    kayit?: string[];
  } = {},
): Env {
  const dosyalar: Record<string, unknown> = {
    "/nowcast.json": opsiyon.kirikVeri ? { aciklama: "şema dışı" } : veri.nowcast,
    "/scores.json": veri.scores,
    "/meta.json": veri.meta,
    "/series/tufe_aylik.json": veri.seriler?.[0],
    "/": "<html>yer tutucu</html>",
    "/m/": "<html>mobil</html>",
    "/en/": "<html>ingilizce</html>",
    "/site.js": "export {}",
  };
  if (opsiyon.seriYok) delete dosyalar["/series/tufe_aylik.json"];
  return {
    MOCK: opsiyon.mock === false ? undefined : "1",
    AI: {
      run: async () => {
        throw new Error("MOCK modunda AI çağrısı yapıldı — bu bir test hatasıdır");
      },
    } as unknown as Env["AI"],
    ASSETS: {
      fetch: async (istek: Request) => {
        const yol = new URL(istek.url).pathname;
        opsiyon.kayit?.push(yol);
        if (!(yol in dosyalar)) return new Response("bulunamadı", { status: 404 });
        return new Response(JSON.stringify(dosyalar[yol]));
      },
    } as unknown as Env["ASSETS"],
  };
}

export const ctx = {
  waitUntil() {},
  passThroughOnException() {},
} as unknown as ExecutionContext;

// worker.fetch handler imzasındaki CfProperties generic'ini test tarafında sadeleştirir.
export const calistir = worker.fetch as unknown as (
  istek: Request,
  ortam: Env,
  baglam: ExecutionContext,
) => Promise<Response>;

export const MOBIL_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
export const MASAUSTU_UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
