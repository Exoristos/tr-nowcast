// site/tests/guardrail.test.ts — T24 guardrail: sayı doğrulama + tavsiye kalkanı.
// Review Focus 2: cevapta bağlamda olmayan sayı → "dikkat" alanı dolu; sessiz geçiş yok.
import { describe, expect, it } from "vitest";
import { dogrula } from "../src/dogrula";
import {
  derle,
  kesinlikCevabi,
  KESINLIK_SABIT_SAYILARI,
  TAVSIYE_REDI,
  VERI_DISI_REDI,
  YAPIM_BILGISI,
  yapimSorulariMi,
} from "../src/prompt";
import worker, { type Env } from "../src/worker";
import { veri } from "./veri";

const BAGLAM = derle("enflasyon tahmini nedir?", veri).baglam;

// AI binding'i verilen metni cevap olarak döndüren mock ortam; MOCK kapalıdır,
// böylece worker'ın gerçek (LLM sonrası) doğrulama yolu test edilir. AI çağrısı
// yine mock'tur — dışa çıkış olmaz.
function mockEnv(aiCevap: string): Env {
  return {
    MOCK: undefined,
    AI: {
      run: async () => ({ response: aiCevap }),
    } as unknown as Env["AI"],
    ASSETS: {
      fetch: async (istek: Request) => {
        const yol = new URL(istek.url).pathname;
        const govde: Record<string, unknown> = {
          "/nowcast.json": veri.nowcast,
          "/scores.json": veri.scores,
          "/meta.json": veri.meta,
          "/series/tufe_aylik.json": veri.seriler?.[0],
        };
        if (!(yol in govde)) return new Response("bulunamadı", { status: 404 });
        return new Response(JSON.stringify(govde[yol]));
      },
    } as unknown as Env["ASSETS"],
  };
}

const ctx = {
  waitUntil() {},
  passThroughOnException() {},
} as unknown as ExecutionContext;

const calistir = worker.fetch as unknown as (
  istek: Request,
  ortam: Env,
  baglam: ExecutionContext,
) => Promise<Response>;

async function sohbet(soru: string, ortam: Env): Promise<Record<string, unknown>> {
  const istek = new Request("https://site.test/api/sohbet", {
    method: "POST",
    body: JSON.stringify({ soru }),
  });
  const yanit = await calistir(istek, ortam, ctx);
  return (await yanit.json()) as Record<string, unknown>;
}

describe("dogrula — sayı doğrulama (Review Focus 2)", () => {
  it("bağlamda olmayan sayı → uyari dolu (sessiz geçiş yok)", () => {
    const { uyari } = dogrula("Aylık tahmin %7.77 civarında.", BAGLAM);
    expect(uyari).toBe("cevapta doğrulanamayan sayı var");
  });

  it("bağlamdaki sayılar → uyari null", () => {
    const { uyari } = dogrula(
      "Aylık tahmin %2.58 (bant 0.92–4.24); yıllık %31.47; arima MAE 1.25, " +
        "n=94; hedef ay 2026-11, seri 2026-10:2.74.",
      BAGLAM,
    );
    expect(uyari).toBeNull();
  });

  it("karışık cevapta tek bağlam-dışı sayı bile uyarı üretir", () => {
    const { uyari } = dogrula("Aylık tahmin %2.58, güven bantı %80, MAE 3.33.", BAGLAM);
    expect(uyari).toBe("cevapta doğrulanamayan sayı var");
  });

  it("TR ondalık virgülü (%2,58) bağlam sayısıyla eşleşir", () => {
    const { uyari } = dogrula("Aylık tahmin %2,58.", BAGLAM);
    expect(uyari).toBeNull();
  });

  it("tarih aralığı yazımı (2026-11) yanlış negatif sayı üretmez", () => {
    const { uyari } = dogrula("2026-11 ayı için bant 0.92-4.24.", BAGLAM);
    expect(uyari).toBeNull();
  });

  it("sabit red şablonları sayı içermez, doğrulamadan geçer", () => {
    expect(dogrula(TAVSIYE_REDI, BAGLAM).uyari).toBeNull();
    expect(dogrula(VERI_DISI_REDI, BAGLAM).uyari).toBeNull();
  });

  it("%80 varsayılan olarak beyaz listede DEĞİLDİR; bağlamda yoksa uyarılır", () => {
    const skorSuz = { ...veri, scores: { ...veri.scores, scores: [] } };
    const { uyari } = dogrula("Enflasyon %80 oldu.", derle("ne?", skorSuz).baglam);
    expect(uyari).toBe("cevapta doğrulanamayan sayı var");
  });

  it("%80 yalnız kesinlik şablonunun sabit setiyle beyaz listelenir", () => {
    const skorSuz = { ...veri, scores: { ...veri.scores, scores: [] } };
    const cevap = kesinlikCevabi(skorSuz);
    expect(cevap).toContain("%80");
    const { uyari } = dogrula(
      cevap,
      derle("kesin mi?", skorSuz).baglam,
      KESINLIK_SABIT_SAYILARI,
    );
    expect(uyari).toBeNull();
  });

  it("kullanıcının sorusuna gömdüğü sayı doğrulanmış sayılmaz (RF2 deliği kapalı)", () => {
    const { baglam } = derle("enflasyon %45 mi oldu?", veri);
    const { uyari } = dogrula("Evet, aylık %45.", baglam);
    expect(uyari).toBe("cevapta doğrulanamayan sayı var");
  });

  it("kesinlik cevabı (kod üretimi) bağlam sayılarıyla tam uyarlıdır", () => {
    const { uyari } = dogrula(kesinlikCevabi(veri), BAGLAM);
    expect(uyari).toBeNull();
  });
});

describe("/api/sohbet — guardrail entegrasyonu", () => {
  it("RF2: LLM cevabı bağlam-dışı sayı içeriyorsa dikkat dolu döner, sessiz geçilmez", async () => {
    const govde = await sohbet("bu ay enflasyon tahmini nedir?", mockEnv("Aylık tahmin %9.99."));
    expect(govde.kaynak).toBe("veri");
    expect(govde.dikkat).toBe("cevapta doğrulanamayan sayı var");
  });

  it("RF2: kullanıcı sorusundaki sayıyı LLM yankılarsa da dikkat dolu döner", async () => {
    const govde = await sohbet("enflasyon %45 mi oldu?", mockEnv("Evet, aylık %45."));
    expect(govde.kaynak).toBe("veri");
    expect(govde.dikkat).toBe("cevapta doğrulanamayan sayı var");
  });

  it("LLM cevabı bağlam sayılarını kullanıyorsa dikkat null", async () => {
    const govde = await sohbet(
      "bu ay enflasyon tahmini nedir?",
      mockEnv("Aylık tahmin %2.58; arima MAE 1.25."),
    );
    expect(govde.kaynak).toBe("veri");
    expect(govde.dikkat).toBeNull();
  });

  it("RF4: tavsiye sorusu LLM'e gitmez, sabit şablon + dikkat null döner", async () => {
    const govde = await sohbet("hangi modelden alayım?", mockEnv("asla çağrılmamalı"));
    expect(govde.kaynak).toBe("tavsiye_redi");
    expect(govde.cevap).toBe(TAVSIYE_REDI);
    expect(govde.dikkat).toBeNull();
  });

  it("RF1: TR ve EN veri-dışı sorular mock modda red kalıbıyla döner, dikkat null", async () => {
    for (const soru of ["Türkiye'nin GSMH büyümesi ne kadar?", "What is the GDP growth rate?"]) {
      const ortam = { ...mockEnv("asla çağrılmamalı"), MOCK: "1" };
      const govde = await sohbet(soru, ortam);
      expect(govde.kaynak).toBe("red");
      expect(govde.cevap).toBe(VERI_DISI_REDI);
      expect(govde.dikkat).toBeNull();
    }
  });

  it("kesinlik yolu kod üretimi olduğundan dikkat null döner", async () => {
    const govde = await sohbet("tahmin kesin mi?", mockEnv("asla çağrılmamalı"));
    expect(govde.kaynak).toBe("veri");
    expect(govde.dikkat).toBeNull();
  });

  it("mock mod: bağlamın kendisi döndüğünden dikkat null", async () => {
    const govde = await sohbet("bu ay enflasyon tahmini nedir?", {
      ...mockEnv("asla çağrılmamalı"),
      MOCK: "1",
    });
    expect(govde.kaynak).toBe("veri");
    expect(govde.dikkat).toBeNull();
  });

  it("mock mod: yankılanan bağlam kendi kaynağıyla doğrulanır; sorudaki sayı bile uyarı üretmez", async () => {
    const govde = await sohbet("enflasyon %45 mi oldu?", {
      ...mockEnv("asla çağrılmamalı"),
      MOCK: "1",
    });
    expect(govde.kaynak).toBe("veri");
    expect(govde.dikkat).toBeNull();
  });
});

describe("yapım bilgisi kalkanı — 'kim yaptı?' soruları kod seviyesinde cevaplanır", () => {
  it("yapimSorulariMi: TR ve EN yapım sorularını yakalar", () => {
    expect(yapimSorulariMi("bu siteyi kim yaptı?")).toBe(true);
    expect(yapimSorulariMi("Bu projeyi kim geliştirdi?")).toBe(true);
    expect(yapimSorulariMi("Bu modeli kim yazdı?")).toBe(true);
    expect(yapimSorulariMi("who developed this?")).toBe(true);
    expect(yapimSorulariMi("Who made this site?")).toBe(true);
  });

  it("yapimSorulariMi: veri soruları ve 'kimin/kim' soruları yakalanmaz", () => {
    expect(yapimSorulariMi("Kasım tahmini neden bu?")).toBe(false);
    expect(yapimSorulariMi("Hangi model en iyi?")).toBe(false);
    expect(yapimSorulariMi("kimin tahmini daha isabetli?")).toBe(false);
    expect(yapimSorulariMi("TCMB başkanı kim?")).toBe(false);
  });

  it("YAPIM_BILGISI sabit sayı içermez, doğrulamadan geçer", () => {
    expect(dogrula(YAPIM_BILGISI, BAGLAM).uyari).toBeNull();
  });

  it("kim yaptı sorusu LLM'e gitmez, sabit yapım cevabı döner", async () => {
    const govde = await sohbet("bu siteyi kim yaptı?", mockEnv("asla çağrılmamalı"));
    expect(govde.kaynak).toBe("yapim");
    expect(govde.cevap).toBe(YAPIM_BILGISI);
    expect(String(govde.cevap)).toContain("Enis Erdoğan");
    expect(govde.dikkat).toBeNull();
  });
});
