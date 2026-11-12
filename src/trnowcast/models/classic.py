"""ARIMA ve ETS benchmark modelleri (T13) — statsmodels.

ARIMA: order=(1,0,0) sabit, bant statsmodels ``conf_int(alpha=0.20)`` (%80).
ETS: ``ExponentialSmoothing`` (trend="add", mevsimsellik yok — aylık % serisi
kısa/şoklu). Yakınsama hatası, NaN çıktı veya tekil (sabit) seri → ModelFailure;
motor bunu FailedForecast olarak sayar, sessiz 0 döndürmez (Review Focus 4).

Yakınsama: statsmodels yakınsamayan fit için exception fırlatmaz, yalnız
ConvergenceWarning basar; o yüzden iki kapı da denetlenir — (1) uyarı error'a
dönüştürülür, (2) ``mle_retvals`` içindeki ``converged``/``success`` bayrağı
kontrol edilir. İkisi de değilse sonlu çıktıya güvenilir.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from trnowcast.backtest import ForecastPoint, ModelFailure

# %80 aralığın normal yaklaşım çeyreği: ExponentialSmoothing'in conf_int'i yok;
# bant = bu çeyrek x kalıntı std'si ile kurulur.
Z80 = 1.2815515655446004

_VARSAYILAN_HEDEF = "turkiye_tufe_aylik_yuzde"


def _hedef_dizi(kesit: dict[str, pd.DataFrame], target: str, model: str) -> pd.Series:
    if target not in kesit or kesit[target].empty:
        raise ModelFailure(f"{model}: hedef seri kesitte yok ({target})")
    s = kesit[target]["value"].astype(float).dropna()
    if len(s) < 2:
        raise ModelFailure(f"{model}: yetersiz geçmiş ({len(s)} gözlem)")
    if float(np.nanstd(s.to_numpy())) == 0.0:
        # Tekil seri: varyans 0 → CI/bant tanımsız; fit etmeden başarısız say.
        raise ModelFailure(f"{model}: tekil (sabit) seri — bant tanımsız")
    return s


def _adim(sayi: pd.Series, hedef_ay: pd.Timestamp, model: str) -> int:
    """Kesitteki son aydan hedef aya kadar kaç adım ileri tahmin gerektiği."""
    fark = pd.Timestamp(hedef_ay).to_period("M") - sayi.index[-1].to_period("M")
    if fark.n < 1:
        raise ModelFailure(f"{model}: hedef ay kesitte zaten yayında ({hedef_ay:%Y-%m})")
    return fark.n


def _duzenli_indeks(s: pd.Series) -> pd.Series:
    # asof kesitinde ay boşlukları olabilir; statsmodels frekans uyarısı vermemesi
    # ve adımların doğru sayılması için kesintisiz ay-başı indeksi kur.
    return pd.Series(
        s.to_numpy(), index=pd.date_range(s.index[0], periods=len(s), freq="MS"), name="value"
    )


def _yakinsama_kontrol(fit: object, model: str) -> None:
    """Optimizer bayrağı False ise sonlu çıktıya güvenme (ModelFailure)."""
    retvals = getattr(fit, "mle_retvals", None)
    if isinstance(retvals, dict) and (
        retvals.get("converged") is False or retvals.get("success") is False
    ):
        raise ModelFailure(f"{model}: optimizer yakınsamadı")


def _fit_yakinsamayla(model_uretici, model: str):
    """Fit'i çalıştırır; ConvergenceWarning'i error'a çevirip bayrağı denetler."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            fit = model_uretici().fit()
        except ModelFailure:
            raise
        except Exception as hata:
            raise ModelFailure(f"{model} başarısız: {hata}") from hata
    _yakinsama_kontrol(fit, model)
    return fit


def arima(
    kesit: dict[str, pd.DataFrame],
    hedef_ay: pd.Timestamp,
    target: str = _VARSAYILAN_HEDEF,
) -> ForecastPoint:
    s = _duzenli_indeks(_hedef_dizi(kesit, target, "arima"))
    adim = _adim(s, hedef_ay, "arima")
    try:
        fit = _fit_yakinsamayla(lambda: ARIMA(s, order=(1, 0, 0)), "arima")
        tahmin = fit.get_forecast(steps=adim)
        ci = tahmin.conf_int(alpha=0.20)
        nokta = float(tahmin.predicted_mean.iloc[-1])
        alt, ust = float(ci.iloc[-1, 0]), float(ci.iloc[-1, 1])
    except ModelFailure:
        raise
    except Exception as hata:
        raise ModelFailure(f"arima başarısız: {hata}") from hata
    if not all(np.isfinite([nokta, alt, ust])):
        raise ModelFailure("arima: tahmin NaN/inf")
    return ForecastPoint(
        target_month=hedef_ay, point=nokta, lower=alt, upper=ust, model="arima"
    )


def ets(
    kesit: dict[str, pd.DataFrame],
    hedef_ay: pd.Timestamp,
    target: str = _VARSAYILAN_HEDEF,
) -> ForecastPoint:
    s = _hedef_dizi(kesit, target, "ets")
    adim = _adim(s, hedef_ay, "ets")
    try:
        fit = _fit_yakinsamayla(
            lambda: ExponentialSmoothing(s.to_numpy(), trend="add", seasonal=None), "ets"
        )
        nokta = float(fit.forecast(adim)[-1])
    except ModelFailure:
        raise
    except Exception as hata:
        raise ModelFailure(f"ets başarısız: {hata}") from hata
    if not np.isfinite(nokta):
        raise ModelFailure("ets: tahmin NaN/inf")
    kalinti = np.asarray(fit.resid, dtype=float)
    std = float(np.nanstd(kalinti))
    if not np.isfinite(std):
        raise ModelFailure("ets: kalıntı std'si tanımsız")
    bant = Z80 * std
    return ForecastPoint(
        target_month=hedef_ay, point=nokta, lower=nokta - bant, upper=nokta + bant, model="ets"
    )
