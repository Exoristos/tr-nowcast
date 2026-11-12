// site/tests/yonlendirme.test.ts — mobil UA yönlendirmesi ve /tr-nowcast önek soyma.
// İki taban birden test edilir: workers.dev kökü (öneksiz) ve exoristos.dev/tr-nowcast.
// RF4: yönlendirmeler döngüsüz olmalı (/m/ ve /tr-nowcast/m/ kendine 302 atmaz).
import { describe, expect, it } from "vitest";
import { calistir, ctx, MASAUSTU_UA, mockEnv, MOBIL_UA } from "./ortam";
import { veri } from "./veri";

describe("UA yönlendirme (T27, RF4: döngü yok)", () => {
  it("mobil UA ile GET / → 302, Location /m/", async () => {
    const istek = new Request("https://site.test/", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(302);
    expect(yanit.headers.get("location")).toBe("https://site.test/m/");
  });

  it("mobil UA ile GET /index.html → 302 /m/", async () => {
    const istek = new Request("https://site.test/index.html", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(302);
    expect(yanit.headers.get("location")).toBe("https://site.test/m/");
  });

  it("RF4: mobil UA ile GET /m/ → 200 (kendine 302 atmaz, döngü oluşmaz)", async () => {
    const istek = new Request("https://site.test/m/", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("mobil");
  });

  it("mobil UA ile GET /en/ → 200 (EN masaüstü sayfası yönlendirilmez)", async () => {
    const istek = new Request("https://site.test/en/", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("ingilizce");
  });

  it("masaüstü UA ile GET / → 200 (passthrough)", async () => {
    const istek = new Request("https://site.test/", {
      headers: { "user-agent": MASAUSTU_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("yer tutucu");
  });

  it("mobil UA ile POST /api/sohbet yönlendirilmez (endpoint çalışır)", async () => {
    const istek = new Request("https://site.test/api/sohbet", {
      method: "POST",
      headers: { "user-agent": MOBIL_UA, "content-type": "application/json" },
      body: JSON.stringify({ soru: "enflasyon ne?" }),
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
  });
});

describe("base-path öneki (/tr-nowcast altında da servis)", () => {
  it("POST /tr-nowcast/api/sohbet → önek soyulur, sohbet akışı çalışır", async () => {
    const istek = new Request("https://site.test/tr-nowcast/api/sohbet", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ soru: "Yatırım için hangi modelden alayım?" }),
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    const govde = (await yanit.json()) as Record<string, unknown>;
    expect(govde.kaynak).toBe("tavsiye_redi");
  });

  it("GET /tr-nowcast/nowcast.json → ASSETS /nowcast.json yolunu görür, gövde aynen döner", async () => {
    const giden: string[] = [];
    const istek = new Request("https://site.test/tr-nowcast/nowcast.json");
    const yanit = await calistir(istek, mockEnv({ kayit: giden }), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.json()).toEqual(veri.nowcast);
    expect(giden).toEqual(["/nowcast.json"]);
  });

  it("GET /tr-nowcast/ (masaüstü) → ASSETS kökü (/) servis eder", async () => {
    const giden: string[] = [];
    const istek = new Request("https://site.test/tr-nowcast/", {
      headers: { "user-agent": MASAUSTU_UA },
    });
    const yanit = await calistir(istek, mockEnv({ kayit: giden }), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("yer tutucu");
    expect(giden).toEqual(["/"]);
  });

  it("slash'sız /tr-nowcast → 308 /tr-nowcast/ (göreli URL tabanı ancak böyle doğru kurulur)", async () => {
    const istek = new Request("https://site.test/tr-nowcast", {
      headers: { "user-agent": MASAUSTU_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(308);
    expect(yanit.headers.get("location")).toBe("https://site.test/tr-nowcast/");
  });

  it("slash'sız /tr-nowcast/en → 308 /tr-nowcast/en/ (dizin normalleşir, önek korunur)", async () => {
    const istek = new Request("https://site.test/tr-nowcast/en", {
      headers: { "user-agent": MASAUSTU_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(308);
    expect(yanit.headers.get("location")).toBe("https://site.test/tr-nowcast/en/");
  });

  it("mobil UA GET /tr-nowcast/ → 302 /tr-nowcast/m/", async () => {
    const istek = new Request("https://site.test/tr-nowcast/", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(302);
    expect(yanit.headers.get("location")).toBe("https://site.test/tr-nowcast/m/");
  });

  it("RF4: mobil UA GET /tr-nowcast/m/ → 200 (kendine 302 atmaz, döngü yok)", async () => {
    const istek = new Request("https://site.test/tr-nowcast/m/", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("mobil");
  });

  it("mobil UA GET /tr-nowcast/en/ → 200 (EN sayfası önek altında da yönlendirilmez)", async () => {
    const istek = new Request("https://site.test/tr-nowcast/en/", {
      headers: { "user-agent": MOBIL_UA },
    });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(200);
    expect(await yanit.text()).toContain("ingilizce");
  });

  it("GET /tr-nowcast/api/sohbet → 405 (dizin normalleştirmesi sohbete dokunmaz)", async () => {
    const istek = new Request("https://site.test/tr-nowcast/api/sohbet", { method: "GET" });
    const yanit = await calistir(istek, mockEnv(), ctx);
    expect(yanit.status).toBe(405);
  });
});
