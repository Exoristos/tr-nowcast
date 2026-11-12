"""Kalite kontrolleri (Faz 0 / T7).

Depodaki her seri için dört kontrol:
1. "tarih sırası": depodaki satır düzeni (series_id, date) artan sıralamasıyla
   birebir aynı — T2 deposunun yazım sözleşmesinin denetimi.
2. "tekilleştirme": (series_id, date) çiftleri tekil — idempotent yeniden çekim
   sözleşmesi (Review Focus 3: aynı veriyi iki kez çekmek duplicate üretmez).
3. "nan oranı": NaN oranı registry'deki SeriesMeta.nan_threshold değerinden
   kesin küçük; eşik kodda sabit değil, meta'dan gelir.
4. "değer aralığı": uyarı eşiği registry/meta'dan gelir (SeriesMeta.warn_range;
   Review Focus 5: eşikler registry/meta'dan gelmeli). Eşiği seri tanımlandığı
   kaynak modülü üstverisi olarak verir; bu modülde seri adına göre eşik
   tutulmaz. Aralık dışı değer UYARI'dır, hard-fail değildir — 2021-2022
   enflasyon zirveleri (aylık ~%5-13) TÜFE aylık için tanımlı [-2, 20] uyarı
   aralığında kalır ve kontrolü geçer.

Sonuç sözleşmesi: yapısal bozukluklar passed=False üretir (CLI'da hard-fail →
exit 1); uyarı düzeyi bulgular passed=True + detail "UYARI:" önekiyle bildirilir.
CheckResult alanları plan T7'de sabitlendiği için şiddet (severity) bu ikiliyle
kodlanır.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trnowcast.store import load_series, registry


@dataclass
class CheckResult:
    """Tek kalite kontrolünün sonucu. passed=False → hard-fail; uyarı →
    passed=True ve detail "UYARI:" ile başlar (bkz. modül docstring'i)."""

    check: str
    passed: bool
    detail: str


def _sira_kontrolu(df: pd.DataFrame) -> CheckResult:
    sirali = df.sort_values(["series_id", "date"], kind="stable").reset_index(drop=True)
    mevcut = df.reset_index(drop=True)
    if mevcut.equals(sirali):
        return CheckResult("tarih sırası", True, f"{len(df)} satır (series_id, date) artan sırada")
    farkli = (mevcut["date"].values != sirali["date"].values) | (
        mevcut["series_id"].values != sirali["series_id"].values
    )
    i = int(farkli.argmax())
    bulunan = mevcut.iloc[i]
    beklenen = sirali.iloc[i]
    return CheckResult(
        "tarih sırası",
        False,
        f"satır {i}: depoda {bulunan['date']:%Y-%m-%d} ({bulunan['series_id']}), "
        f"beklenen {beklenen['date']:%Y-%m-%d} ({beklenen['series_id']})",
    )


def _tekillestirme_kontrolu(df: pd.DataFrame) -> CheckResult:
    fazla = df.duplicated(subset=["series_id", "date"], keep="first")
    adet = int(fazla.sum())
    if not adet:
        return CheckResult("tekilleştirme", True, "mükerrer (series_id, date) satır yok")
    ornek = df.loc[fazla, "date"].iloc[0]
    return CheckResult(
        "tekilleştirme",
        False,
        f"{adet} mükerrer (series_id, date) satır (örn. {ornek:%Y-%m-%d})",
    )


def _nan_orani_kontrolu(name: str, df: pd.DataFrame, meta: dict) -> CheckResult:
    nan_sayisi = int(df["value"].isna().sum())
    oran = nan_sayisi / len(df)
    esik = float(meta["nan_threshold"])
    passed = oran < esik
    return CheckResult(
        "nan oranı",
        passed,
        f"NaN oranı {oran:.3f}, meta eşiği {esik:.3f} ({nan_sayisi} NaN / {len(df)} satır)",
    )


def _aralik_kontrolu(name: str, df: pd.DataFrame, meta: dict) -> CheckResult:
    # Eşik kaynağı serinin meta'sıdır (registry girdisi); JSON'a liste olarak
    # yazıldığından tuple/list ikisi de kabul edilir.
    aralik = meta.get("warn_range")
    if aralik is None:
        return CheckResult(
            "değer aralığı", True, "uyarı aralığı tanımlı değil — kontrol atlandı"
        )
    alt, ust = aralik
    disarida = df["value"].notna() & ((df["value"] < alt) | (df["value"] > ust))
    adet = int(disarida.sum())
    if not adet:
        return CheckResult(
            "değer aralığı", True, f"tüm {len(df)} gözlem [{alt}, {ust}] aralığında"
        )
    ornek = df.loc[disarida].head(3)
    ornek_metni = "; ".join(f"{t:%Y-%m-%d}: {v}" for t, v in zip(ornek["date"], ornek["value"]))
    return CheckResult(
        "değer aralığı",
        True,
        f"UYARI: {adet} gözlem [{alt}, {ust}] aralığının dışında (örn. {ornek_metni})",
    )


def check_series(name: str) -> list[CheckResult]:
    """Registry'deki bir seriyi dört kontrolden geçirir; sonuç listesi döndürür.

    Seri registry'de yoksa KeyError fırlatır (load_series ile aynı sözleşme).
    """
    kayit = registry()
    if name not in kayit:
        raise KeyError(f"seri registry'de yok: {name!r} — önce 'trnowcast fetch' çalıştırın")
    meta = kayit[name]
    df = load_series(name)
    if df.empty:
        return [
            CheckResult(
                "seri boş",
                False,
                f"{name} parquet'i boş — veri hattı sözleşmesi bozulmuş olabilir",
            )
        ]
    return [
        _sira_kontrolu(df),
        _tekillestirme_kontrolu(df),
        _nan_orani_kontrolu(name, df, meta),
        _aralik_kontrolu(name, df, meta),
    ]
