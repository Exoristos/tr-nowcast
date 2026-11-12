"""TimesFM 3.0 adapter (T16) — çok değişkenli + sürücü kovaryatı.

Google TimesFM 3.0 (``google/timesfm-3.0-pytorch``, timesfm 3.0.2 pypı) aylık
hedef seriyi bağlam olarak alır; sürücüler (usd_try_gunluk, brent_gunluk,
fao_gida_endeks — motor kesitinde zaten aylık ortalamaya kesilmiş) geçmiş
kovaryatı (``past_only_covariates``) olarak geçer: kesitte yalnız t≤cutoff
değerleri vardır, sızıntı yapısal olarak imkânsız (Review Focus 1). Nokta =
medyan (forecast), bant = %10/%90 quantile (varsayılan quantile başlığının
ilk/son sütunu) — planın %80 bandı kuralı.

Review Focus 2: TimesFM 3.0'ın min bağlamı tek 32'lik patch'tir; TÜFE aylık
serisi (~200 gözlem) doğrudan kabul edilir — frekans yayma / uydurma doldurma
YOK. Kısa kesit (<24 gözlem) ModelFailure döner. Ay boşlukları NaN kalır,
model kendi içinde maskeler.

Review Focus 3: timesfm[torch] ekstra 'torch>=2.0.0' ister; T15'in kurduğu
torch 2.11.0+cu128 ile çakışmaz — tek bağımlılık grubu, ayrı venv gerekmedi.

Ağır importlar (torch/timesfm) fonksiyon içinde lazy: CLI'ın diğer komutları
ağı yüklemeden çalışır. GPU yoksa CPU'ya düşer ve log'a yazar.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from trnowcast.backtest import ForecastPoint, ModelFailure

MODEL_ID = "google/timesfm-3.0-pytorch"
MODEL_ADI = "timesfm3_mv"
# Plan Review Focus 2: kısa kesitte ModelFailure (frekans yayma ile bağlam
# uydurma YASAK); 24 Chronos-2 adapter'ıyla aynı taban.
MIN_GOZLEM = 24
SURLULER = ("usd_try_gunluk", "brent_gunluk", "fao_gida_endeks")
# TimesFM 3.0 ModelConfig varsayılan quantile başlığı: %10..%90, medyan sütun
# 4. Bant için yalnız ilk (%10) ve son (%90) sütunu kullanırız.
DEFAULT_QUANTILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

logger = logging.getLogger(__name__)

_forecaster_cache = None


def _forecaster_yukle(model_id: str = MODEL_ID):
    # Ağır importlar burada: torch/timesfm yalnız model ilk koşulduğunda yüklenir.
    import torch
    from timesfm import TimesFM3Forecaster

    if torch.cuda.is_available():
        cihaz = "cuda"
    else:
        cihaz = "cpu"
        logger.warning("timesfm3_mv: GPU bulunamadı, CPU'ya düşülüyor (yavaş)")
    return TimesFM3Forecaster.from_pretrained(model_id, device=cihaz)


def _forecaster():
    global _forecaster_cache
    if _forecaster_cache is None:
        logger.info("timesfm3_mv: %s yükleniyor...", MODEL_ID)
        _forecaster_cache = _forecaster_yukle()
    return _forecaster_cache


def _hedef_seri(kesit: dict[str, pd.DataFrame], target: str) -> pd.Series:
    if target not in kesit or kesit[target].empty:
        raise ModelFailure(f"{MODEL_ADI}: hedef seri kesitte yok ({target})")
    s = kesit[target]["value"].astype(float).dropna()
    if len(s) < MIN_GOZLEM:
        raise ModelFailure(f"{MODEL_ADI}: yetersiz geçmiş ({len(s)} < {MIN_GOZLEM} gözlem)")
    return s


def TIMESFM3_MV(
    kesit: dict[str, pd.DataFrame], hedef_ay: pd.Timestamp, target: str
) -> ForecastPoint:
    s = _hedef_seri(kesit, target)
    hedef_p = pd.Timestamp(hedef_ay).to_period("M")
    adim = (hedef_p - s.index[-1].to_period("M")).n
    if adim < 1:
        raise ModelFailure(f"{MODEL_ADI}: hedef ay kesitte zaten yayında ({hedef_ay:%Y-%m})")

    # Ay boşluklarını değer uydurmadan geç: eksik aylar NaN kalır; TimesFM
    # eksik bağlamı kendi ön işlemesinde maskeler (uydurma veri doldurma YASAK).
    tam_indeks = pd.date_range(s.index[0], s.index[-1], freq="MS")
    context = s.reindex(tam_indeks).to_numpy(dtype=float)

    # Sürücü kovaryatı: (k, T); her satır hedef bağlam indeksine hizalı.
    satirlar: list[np.ndarray] = []
    for ad in SURLULER:
        df = kesit.get(ad)
        if df is None or df.empty:
            continue
        satirlar.append(df["value"].astype(float).reindex(tam_indeks).to_numpy())
    cov = np.stack(satirlar) if satirlar else None

    # Model yükleme try DIŞINDA: ağırlık/CUDA hatası sistematiktir —
    # ModelFailure'e sarılırsa motor her ay sessiz NaN yazar ve kalıcı arıza
    # tek-aylık başarısızlıktan ayırt edilmez (denetçi bulgusu). Yükleme
    # hatası bir kez, görünür şekilde çöker; yalnız predict tek-aylık
    # ModelFailure'e sarılır.
    forecaster = _forecaster()
    try:
        out = forecaster.predict(
            context, horizon=adim, past_only_covariates=cov, return_quantiles=True
        )
    except ModelFailure:
        raise
    except Exception as hata:
        raise ModelFailure(f"{MODEL_ADI} başarısız: {hata}") from hata

    # Son adım = hedef ay (motorun istediği ay). Medyan = forecast; %80 bant
    # quantile başlığının ilk (0.1) ve son (0.9) sütunundan.
    nokta = float(np.asarray(out.forecast)[-1])
    q = np.asarray(out.quantiles)[-1]
    alt, ust = float(q[0]), float(q[-1])
    if not all(np.isfinite([nokta, alt, ust])):
        raise ModelFailure(f"{MODEL_ADI}: tahmin NaN/inf")
    return ForecastPoint(
        target_month=pd.Timestamp(hedef_ay), point=nokta, lower=alt, upper=ust, model=MODEL_ADI
    )
