// site/tests/veri.ts — README'deki data/site JSON şemalarına birebir uyan ortak fikstür.
import type { SeriVeri, SiteVeri } from "../src/prompt";

export const veri: SiteVeri = {
  nowcast: {
    generated_at: "2026-11-07",
    cutoff_date: "2026-11-07",
    target_month: "2026-11",
    forecasts: [
      { model: "naive", point: 2.58, lower: 0.92, upper: 4.24, ok: true, error: null },
      { model: "arima", point: 2.18, lower: 0.2, upper: 4.17, ok: true, error: null },
      {
        model: "anket_pka",
        point: null,
        lower: null,
        upper: null,
        ok: false,
        error: "anket satırı kesitte yok",
      },
    ],
    yillik: {
      point: 31.47,
      lower: 29.52,
      upper: 33.26,
      temel: "son 11 gerçek ay + hedef tahmini",
    },
  },
  scores: {
    generated_at: "2026-11-07",
    windows: ["2019→bugün"],
    scores: [
      {
        model: "arima",
        window: "2019→bugün",
        mae: 1.25,
        rmse: 2.08,
        n: 94,
        n_failed: 0,
        hit80_rate: 0.787,
      },
    ],
  },
  meta: {
    generated_at: "2026-11-07",
    registry: {
      tufe_aylik: { source: "TCMB EVDS", url: "https://evds2.tcmb.gov.tr" },
    },
  },
  // 13 nokta: 2025-10 → 2026-10. derle "son 12 ay" dilimi aldığından ilk ay
  // (2025-10) bağlama sızMAmalı; son değer 2.74 girer.
  seriler: [
    {
      series: "tufe_aylik",
      unit: "% (aylık, türetilmiş)",
      points: Array.from({ length: 13 }, (_, i) => {
        const ay = 9 + i;
        const yil = 2025 + Math.floor(ay / 12);
        return [
          `${yil}-${String((ay % 12) + 1).padStart(2, "0")}-01`,
          2.5 + i * 0.02,
        ] as [string, number];
      }),
    } satisfies SeriVeri,
  ],
};
