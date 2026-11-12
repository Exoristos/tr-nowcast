// site/tests/prompt.test.ts — prompt derleyici ve kesinlik şablonu birim testleri.
import { describe, expect, it } from "vitest";
import { derle, kesinlikCevabi } from "../src/prompt";
import { veri } from "./veri";

describe("derle — prompt derleyici (saf fonksiyon)", () => {
  it("{system, kullanici} döndürür; system guardrail kurallarını taşır", () => {
    const { system, kullanici } = derle("enflasyon tahmini ne?", veri);
    expect(kullanici).toContain("SORU: enflasyon tahmini ne?");
    expect(system).toContain("verimde yok");
    expect(system).toContain("kesinlik");
    expect(system).toContain("Yatırım");
  });

  it("kullanıcı mesajı bağlam özetini taşır: hedef ay, model adı, MAE", () => {
    const { kullanici } = derle("arima bu ay ne diyor?", veri);
    expect(kullanici).toContain("2026-11");
    expect(kullanici).toContain("naive");
    expect(kullanici).toContain("tahmin yok"); // başarısız model satırı
    expect(kullanici).toContain("1.25"); // arima MAE
  });

  it("RF1: soru veri-dışı olsa bile derlenen BAĞLAM bölümüne GSMH sızmaz", () => {
    const { kullanici } = derle("GSMH kaç?", veri);
    const baglam = kullanici.slice(kullanici.indexOf("BAĞLAM")).toLowerCase();
    expect(baglam).not.toContain("gsmh");
  });

  it("derle serileri 'son 12 ay' dilimiyle bağlama ekler", () => {
    const { kullanici } = derle("tufe serisi ne diyor?", veri);
    expect(kullanici).toContain("Seri değerleri");
    expect(kullanici).toContain("tufe_aylik (% (aylık, türetilmiş))");
    expect(kullanici).toContain("2026-10:2.74"); // son nokta
    expect(kullanici).not.toContain("2025-10:"); // 13. nokta dilim dışına düştü
  });
});

describe("kesinlikCevabi — belirsizlik şablonu", () => {
  it("bant ve MAE'lerle belirsizliği anlatır", () => {
    const cevap = kesinlikCevabi(veri);
    expect(cevap).toContain("kesin değil");
    expect(cevap).toContain("%80");
    expect(cevap).toContain("MAE");
    expect(cevap).toContain("31.47"); // yıllık türetme nokta tahmini
    expect(cevap).toContain("1.25"); // arima MAE
  });

  it("yıllık null ise de çalışır", () => {
    const yilliksiz = { ...veri, nowcast: { ...veri.nowcast, yillik: null } };
    const cevap = kesinlikCevabi(yilliksiz);
    expect(cevap).toContain("%80");
    expect(cevap).toContain("MAE");
  });

  it("tüm modeller başarısızsa Infinity üretmez", () => {
    const hepBasarisiz = {
      ...veri,
      scores: { ...veri.scores, scores: [] },
      nowcast: {
        ...veri.nowcast,
        yillik: null,
        forecasts: veri.nowcast.forecasts.map((t) => ({ ...t, ok: false })),
      },
    };
    const cevap = kesinlikCevabi(hepBasarisiz);
    expect(cevap).not.toContain("Infinity");
    expect(cevap).toContain("kesin değildir");
    expect(cevap).toContain("%80");
  });
});
