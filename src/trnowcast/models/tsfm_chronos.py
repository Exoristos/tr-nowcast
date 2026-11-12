"""Chronos-2 zero-shot adapter (T15) — tek değişkenli.

Amazon Chronos-2 (``amazon/chronos-2``) aylık hedef seriyi bağlam olarak alır,
hedef aya kadar öngörür: nokta = 0.5 quantile (medyan), bant = %10/%90 quantile
(planın %80 belirsizlik bandı kuralı). Zero-shot: katsayı fit'i yok.

ModelFn sözleşmesi (Faz 1): yalnız motor kesiti sözlüğüne bakar — ham store
erişimi imzada yok, sızıntı yapısal olarak imkânsız (Review Focus 1).

Ağır importlar (torch/chronos) fonksiyon içinde lazy: CLI'ın diğer komutları
ağı yüklemeden çalışır. GPU yoksa CPU'ya düşer ve log'a yazar.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from trnowcast.backtest import ForecastPoint, ModelFailure

MODEL_ID = "amazon/chronos-2"
MODEL_ADI = "chronos2_uni"
# Plan: kısa kesitte (<24 gözlem) ModelFailure — TÜFE aylık serisi ~200 gözlem,
# 24 Chronos'un kısa bağlam sınırının altında güvenli bir taban.
MIN_GOZLEM = 24

logger = logging.getLogger(__name__)

_pipeline_cache = None


def _pipeline_yukle(model_id: str = MODEL_ID):
    # Ağır importlar burada: torch/chronos yalnız model ilk koşulduğunda yüklenir.
    import torch
    from chronos import Chronos2Pipeline

    if torch.cuda.is_available():
        cihaz = "cuda"
    else:
        cihaz = "cpu"
        logger.warning("chronos2_uni: GPU bulunamadı, CPU'ya düşülüyor (yavaş)")
    return Chronos2Pipeline.from_pretrained(model_id, device_map=cihaz)


def _pipeline():
    global _pipeline_cache
    if _pipeline_cache is None:
        logger.info("chronos2_uni: %s yükleniyor...", MODEL_ID)
        _pipeline_cache = _pipeline_yukle()
    return _pipeline_cache


def _hedef_seri(kesit: dict[str, pd.DataFrame], target: str) -> pd.Series:
    if target not in kesit or kesit[target].empty:
        raise ModelFailure(f"{MODEL_ADI}: hedef seri kesitte yok ({target})")
    s = kesit[target]["value"].astype(float).dropna()
    if len(s) < MIN_GOZLEM:
        raise ModelFailure(f"{MODEL_ADI}: yetersiz geçmiş ({len(s)} < {MIN_GOZLEM} gözlem)")
    return s


def CHRONOS2_UNI(
    kesit: dict[str, pd.DataFrame], hedef_ay: pd.Timestamp, target: str
) -> ForecastPoint:
    s = _hedef_seri(kesit, target)
    hedef_p = pd.Timestamp(hedef_ay).to_period("M")
    adim = (hedef_p - s.index[-1].to_period("M")).n
    if adim < 1:
        raise ModelFailure(f"{MODEL_ADI}: hedef ay kesitte zaten yayında ({hedef_ay:%Y-%m})")

    # Ay boşluklarını değer uydurmadan geç: eksik aylar NaN kalır; Chronos-2
    # eksik bağlamı model içinde maskeleyebilir (uydurma veri doldurma YASAK).
    tam_indeks = pd.date_range(s.index[0], s.index[-1], freq="MS")
    df = pd.DataFrame(
        {
            "item_id": "hedef",
            "timestamp": tam_indeks,
            "target": s.reindex(tam_indeks).to_numpy(),
        }
    )
    try:
        out = _pipeline().predict_df(
            df, prediction_length=adim, quantile_levels=[0.1, 0.5, 0.9], freq="MS"
        )
    except ModelFailure:
        raise
    except Exception as hata:
        raise ModelFailure(f"{MODEL_ADI} başarısız: {hata}") from hata

    # Son adım = hedef ay (motorun istediği ay).
    son = out.iloc[-1]
    nokta, alt, ust = float(son["0.5"]), float(son["0.1"]), float(son["0.9"])
    if not all(np.isfinite([nokta, alt, ust])):
        raise ModelFailure(f"{MODEL_ADI}: tahmin NaN/inf")
    return ForecastPoint(
        target_month=pd.Timestamp(hedef_ay), point=nokta, lower=alt, upper=ust, model=MODEL_ADI
    )
