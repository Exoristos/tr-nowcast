"""Naive ve seasonal-naive benchmark modelleri (T13).

Bant kuralı (plan Global Constraint): eğitim kesitindeki |hata|'nın %80 persentili
tek değer bandı olarak kullanılır (lower=point-band, upper=point+band);
band < 0.2 ise 0.2 alınır. Kesitte 24 aydan az geçmiş varsa ModelFailure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trnowcast.backtest import ForecastPoint, ModelFailure

# Baseline modellerin çalışması için kesitte bulunması gereken en az ay sayısı.
MIN_GECMIS_AY = 24

# Bant tabanı: daha dar bant aşırı güven verir; %80 persentil bunun altına düşerse taban uygulanır.
BANT_TABANI = 0.2

_VARSAYILAN_HEDEF = "turkiye_tufe_aylik_yuzde"


def _hedef_df(kesit: dict[str, pd.DataFrame], target: str, model: str) -> pd.DataFrame:
    if target not in kesit or kesit[target].empty:
        raise ModelFailure(f"{model}: hedef seri kesitte yok ({target})")
    return kesit[target]


def _bant(hatalar: pd.Series, model: str) -> float:
    """Eğitim |hata|'larının %80 persentili, taban 0.2'nin altına düşmez."""
    if hatalar.dropna().empty:
        raise ModelFailure(f"{model}: eğitim hata geçmişi boş")
    persentil = float(np.nanpercentile(hatalar.to_numpy(), 80))
    return max(persentil, BANT_TABANI)


def naive(
    kesit: dict[str, pd.DataFrame],
    hedef_ay: pd.Timestamp,
    target: str = _VARSAYILAN_HEDEF,
) -> ForecastPoint:
    """Son gözlemlenen değer; bant = geçmiş ay-üzeri |değişim| %80 persentili."""
    df = _hedef_df(kesit, target, "naive")
    if len(df) < MIN_GECMIS_AY:
        raise ModelFailure(f"yetersiz geçmiş: {len(df)} ay < {MIN_GECMIS_AY}")
    nokta = float(df["value"].iloc[-1])
    if not np.isfinite(nokta):
        # Sessiz NaN'lı tahmin skoru sessizce düşürür; FailedForecast sayılsın.
        raise ModelFailure("naive: kesitteki son değer NaN/inf")
    bant = _bant(df["value"].diff().abs(), "naive")
    return ForecastPoint(
        target_month=hedef_ay, point=nokta, lower=nokta - bant, upper=nokta + bant, model="naive"
    )


def seasonal_naive(
    kesit: dict[str, pd.DataFrame],
    hedef_ay: pd.Timestamp,
    target: str = _VARSAYILAN_HEDEF,
) -> ForecastPoint:
    """12 ay önceki değer; bant = |v[t] - v[t-12]| %80 persentili."""
    df = _hedef_df(kesit, target, "seasonal_naive")
    if len(df) < MIN_GECMIS_AY:
        raise ModelFailure(f"yetersiz geçmiş: {len(df)} ay < {MIN_GECMIS_AY}")
    kaynak = pd.Timestamp(hedef_ay) - pd.DateOffset(months=12)
    if kaynak not in df.index:
        raise ModelFailure(f"seasonal_naive: kaynak ay kesitte yok ({kaynak:%Y-%m})")
    nokta = float(df.loc[kaynak, "value"])
    if not np.isfinite(nokta):
        raise ModelFailure("seasonal_naive: kaynak ay değeri NaN/inf")
    bant = _bant((df["value"] - df["value"].shift(12)).abs(), "seasonal_naive")
    return ForecastPoint(
        target_month=hedef_ay,
        point=nokta,
        lower=nokta - bant,
        upper=nokta + bant,
        model="seasonal_naive",
    )
