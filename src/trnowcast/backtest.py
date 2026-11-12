"""As-of backtest motoru (T12) — hileye kapalı expanding-window çerçeve.

İlke: her hedef ay M için kesit tarihi cutoff = M ay sonunun + ``CUTOFF_OFFSET_DAYS``
günü sabitlenir; motor her seriyi yalnız cutoff'ta yayında olan aylara kırpar
(registry ``publication_lag_days`` üzerinden) ve modelleri bu kesitlerle besler.
Modeller asla ham parquet'e erişemez: geleceğe sızmanın tek yolu motoru atlamak,
motor da kesiti cutoff'ta kırdığı için sızıntı yapısal olarak imkânsızdır.

Yayın kuralı: X ayı, X ay sonu + lag günü <= cutoff ise kesitte yayında sayılır.
lag=3 seride cutoff (M sonu + 2 gün) M'nin kendi yayın gününe denk gelmez;
son girilen ay M-1'dir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from trnowcast.store import load_series, registry

# Hedef ay M için kesit tarihi = M'nin son günü + bu kadar gün.
CUTOFF_OFFSET_DAYS = 2


@dataclass
class ForecastPoint:
    """Bir modelin tek aylık tahmini; bant %80'dir."""

    target_month: pd.Timestamp
    point: float
    lower: float
    upper: float
    model: str


# İlk argüman: ay-başı indeksli aylık DataFrame sözlüğü ({seri_adı: df});
# günlük seriler aylık ortalamaya kesilmiş, eksik aylara satır hiç yok.
# İkincisi: hedef ay (ay-başı Timestamp). Üçüncüsü: motorun target seri adı —
# modeller hedef seriyi buradan okur; kendi varsayılanıyla değil (denetçi
# bulgusu: motorun serisi modele ulaşmazsa baseline başka kesit okur ve skor
# yanlış actual'a karşı sessizce hesaplanır).
ModelFn = Callable[[dict[str, pd.DataFrame], pd.Timestamp, str], ForecastPoint]


class ModelFailure(Exception):
    """Model o ay tahmin üretemedi (yetersiz geçmiş, yakınsama, NaN...).

    Motor bunu çökme değil normal iş akışı sayar: o (model, ay) satırı
    NaN ile yazılır ve devam edilir.
    """


def asof_monthly(seri: str, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Serinin ``cutoff`` anında yayında olan aylarını ay-başı indeksli döndürür.

    Aylık seri: lag'i dolmuş ayların değerleri. Günlük seri: yalnız TAM ayların
    ortalaması — ayın ilk ve son günü veride yoksa o ay tanımsızdır, satır eklenmez.
    """
    meta = registry().get(seri)
    if meta is None:
        raise KeyError(f"seri registry'de yok: {seri}")
    lag = int(meta["publication_lag_days"])
    df = load_series(seri).sort_values("date", kind="stable")

    ay = df["date"].dt.to_period("M")
    # Yayın kuralı: ay sonu + lag günü <= cutoff → yayında.
    yayinda = ay.dt.end_time.dt.normalize() + pd.Timedelta(days=lag) <= cutoff
    df = df.loc[yayinda]
    ay = ay.loc[yayinda]
    if df.empty:
        return pd.DataFrame(
            {"value": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], name="ay")
        )

    gunluk = meta["frequency"] == "günlük"
    satirlar: list[tuple[pd.Timestamp, float]] = []
    for p, g in df.groupby(ay):
        if gunluk:
            # Tam ay tanımı: ayın TÜM takvim günleri veride olmalı; uçları dolu
            # ama ortası delikli ay (kaynak kesintisi) da TANIMSIZ sayılır.
            gun = g["date"].dt.normalize()
            if gun.nunique() != p.days_in_month:
                continue
            deger = g["value"].mean()
        else:
            deger = g["value"].iloc[-1]
        satirlar.append((p.start_time, float(deger)))
    return (
        pd.DataFrame(satirlar, columns=["ay", "value"])
        .set_index("ay")
        .rename_axis("ay")
    )


def run_backtest(
    models: dict[str, ModelFn],
    target: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Modelleri hedef seri üzerinde ay ay, as-of kesitlerle koşar.

    Sütunlar: model, target_month, point, lower, upper, actual, abs_error, hit80
    (actual bant aralığındaysa True). Satır sırası model → tarih artan.
    ModelFailure fırlatan (model, ay) satırı NaN ile yazılır, motor devam eder.
    """
    bas = pd.Period(pd.Timestamp(start), freq="M")
    son = pd.Period(pd.Timestamp(end), freq="M")
    if bas > son:
        raise ValueError(f"start ({bas}) end'den ({son}) sonra olamaz")

    # Actual, hedef serinin GERÇEK değeridir (tam seriden); skorlama bunu kullanır.
    tam = load_series(target)
    actuals = tam.groupby(tam["date"].dt.to_period("M"))["value"].last()

    # Kesit ay başına bir kez kurulur, modeller arasında paylaşılır.
    kesitler: dict[pd.Period, dict[str, pd.DataFrame]] = {}

    def kesit(p: pd.Period) -> dict[str, pd.DataFrame]:
        if p not in kesitler:
            cutoff = p.end_time.normalize() + pd.Timedelta(days=CUTOFF_OFFSET_DAYS)
            kesitler[p] = {ad: asof_monthly(ad, cutoff) for ad in registry()}
        return kesitler[p]

    satirlar: list[dict] = []
    for model_adi, fn in models.items():
        for p in pd.period_range(bas, son, freq="M"):
            try:
                fp = fn(kesit(p), p.start_time, target)
                point, lower, upper = float(fp.point), float(fp.lower), float(fp.upper)
            except ModelFailure:
                point = lower = upper = np.nan

            actual = float(actuals.get(p, np.nan))
            if np.isfinite(point) and np.isfinite(actual):
                abs_error = abs(point - actual)
                hit80: object = bool(lower <= actual <= upper)
            else:
                abs_error = np.nan
                hit80 = np.nan
            satirlar.append(
                {
                    "model": model_adi,
                    "target_month": p.start_time,
                    "point": point,
                    "lower": lower,
                    "upper": upper,
                    "actual": actual,
                    "abs_error": abs_error,
                    "hit80": hit80,
                }
            )
    return pd.DataFrame(
        satirlar,
        columns=[
            "model",
            "target_month",
            "point",
            "lower",
            "upper",
            "actual",
            "abs_error",
            "hit80",
        ],
    )
