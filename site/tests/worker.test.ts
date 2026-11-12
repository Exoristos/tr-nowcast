// site/tests/worker.test.ts — /api/sohbet kapı testleri (mock binding ile).
// Yönlendirme/önek testleri yonlendirme.test.ts'te, paylaşılan mock ortam ortam.ts'te.
import { describe, expect, it } from "vitest";
import { type SohbetYanit } from "../src/worker";
import { TAVSIYE_REDI, VERI_DISI_REDI } from "../src/prompt";
import { calistir, ctx, mockEnv } from "./ortam";

async function sohbet(
  soru: unknown,
  ortam = mockEnv(),
): Promise<{ durum: number; govde: Record<string, unknown> }> {
  const istek = new Request("https://site.test/api/sohbet", {
    method: "POST",
    body: JSON.stringify({ soru }),
  });
  const yanit = await calistir(istek, ortam, ctx);
  return { durum: yanit.status, govde: (await yanit.json()) as Record<string, unknown> };
}

describe("/api/sohbet — kapı testleri (mock binding)", () => {
  it("RF4: yatırım sorusu kod seviyesinde sabit şablonla reddedilir (LLM'e bırakılmaz)", async () => {
    const { durum, govde } = await sohbet("Yatırım için hangi modelden alayım?");
    expect(durum).toBe(200);
    expect(govde.kaynak).toBe("tavsiye_redi");
    expect(govde.cevap).toBe(TAVSIYE_REDI);
    const ikinci = await sohbet("portföyüme ne alsam?");
    expect(ikinci.govde.kaynak).toBe("tavsiye_redi");
    expect(ikinci.govde.cevap).toBe(TAVSIYE_REDI);
    const ucuncu = await sohbet("altın almalı mıyım?");
    expect(ucuncu.govde.kaynak).toBe("tavsiye_redi");
    const dorduncu = await sohbet("satalım mı?");
    expect(dorduncu.govde.kaynak).toBe("tavsiye_redi");
  });

  it("RF1: veri dışı konular red kalıbıyla döner", async () => {
    const gsmh = await sohbet("Türkiye'nin GSMH büyümesi ne kadar?");
    expect(gsmh.govde.kaynak).toBe("red");
    expect(gsmh.govde.cevap).toBe(VERI_DISI_REDI);
    const dolar = await sohbet("yarın dolar kaç TL olur?");
    expect(dolar.govde.kaynak).toBe("red");
    expect(dolar.govde.cevap).toBe(VERI_DISI_REDI);
  });

  it("RF3: kesinlik sorusu bant ve MAE'lerle belirsizliği anlatır, kesinlik iddia etmez", async () => {
    const { durum, govde } = await sohbet("Bu tahmin kesin mi?");
    expect(durum).toBe(200);
    expect(govde.kaynak).toBe("veri");
    const cevap = govde.cevap as string;
    expect(cevap).toContain("kesin değil");
    expect(cevap).toContain("%80");
    expect(cevap).toContain("MAE");
    expect(cevap).toContain("31.47"); // yıllık türetme nokta tahmini
    expect(cevap).toContain("1.25"); // arima MAE
  });

  it("MOCK=1: veri sorusu derlenen bağlam özetini döndürür, AI çağrılmaz", async () => {
    const { durum, govde } = await sohbet("Bu ay enflasyon tahmini nedir?");
    expect(durum).toBe(200);
    expect(govde.kaynak).toBe("veri");
    const cevap = govde.cevap as string;
    expect(cevap).toContain("MOCK");
    expect(cevap).toContain("2026-11");
    expect(cevap).toContain("naive");
    expect(cevap).toContain("son 12 ay"); // seri değerleri bağlamda
  });

  it("MOCK: geçmiş dolar/kur sorusu seri bağlamıyla veri döner", async () => {
    const { durum, govde } = await sohbet("dolar geçen ay kaçtı?");
    expect(durum).toBe(200);
    expect(govde.kaynak).toBe("veri");
    expect(govde.cevap as string).toContain("son 12 ay");
  });

  it("yanıt şeması: {cevap, kaynak, dikkat: null}", async () => {
    const { govde } = await sohbet("yıllık tahmin ne?");
    expect(Object.keys(govde).sort()).toEqual(["cevap", "dikkat", "kaynak"]);
    expect((govde as unknown as SohbetYanit).dikkat).toBeNull();
  });

  it("boş veya eksik soru → 400", async () => {
    expect((await sohbet("")).durum).toBe(400);
    expect((await sohbet(null)).durum).toBe(400);
    expect((await sohbet(42)).durum).toBe(400);
  });

  it("GET /api/sohbet → 405", async () => {
    const istek = new Request("https://site.test/api/sohbet", { method: "GET" });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(405);
  });

  it("API dışı yol → assets passthrough", async () => {
    const istek = new Request("https://site.test/", { method: "GET" });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("yer tutucu");
  });

  it("MOCK kapalıysa AI yoluna girilir; AI hatası 502 döndürür (gerçek LLM çağrısı yok)", async () => {
    const { durum, govde } = await sohbet("bu ay enflasyon tahmini nedir?", mockEnv({ mock: false }));
    expect(durum).toBe(502);
    expect(govde.kaynak).toBeUndefined();
    expect(govde.hata).toBeDefined();
  });

  it("şema dışı nowcast verisi → JSON gövdeli 503, çökme yok", async () => {
    const { durum, govde } = await sohbet("enflasyon ne?", mockEnv({ kirikVeri: true }));
    expect(durum).toBe(503);
    expect(govde.hata).toBeDefined();
  });

  it("eksik seri dosyası atlanır, endpoint çalışır", async () => {
    const { durum, govde } = await sohbet("bu ay enflasyon tahmini nedir?", mockEnv({ seriYok: true }));
    expect(durum).toBe(200);
    expect(govde.kaynak).toBe("veri");
    expect(govde.cevap as string).not.toContain("tufe_aylik ("); // seri bloku boş
  });
});
