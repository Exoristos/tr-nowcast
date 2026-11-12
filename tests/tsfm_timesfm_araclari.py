"""T16 TimesFM testleri için ortak yardımcılar — test_tsfm_timesfm.py ve
test_tsfm_timesfm_live.py kullanır.

pytest'in prepend import modunda tests/ dizini sys.path'e eklendiğinden bu
modül `from tsfm_timesfm_araclari import ...` ile içe aktarılır; adı test_
öneki taşımadığı için test toplamasına girmez.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from trnowcast.models.tsfm_timesfm import DEFAULT_QUANTILES, SURLULER

TUF = "turkiye_tufe_aylik_yuzde"
USD, BRENT, FAO = SURLULER


def kesit_sozluk(values, start="2018-01-01", seri=TUF):
    idx = pd.date_range(start, periods=len(values), freq="MS")
    df = pd.DataFrame({"value": [float(v) for v in values]}, index=idx)
    df.index.name = "ay"
    return {seri: df}


def sonraki_ay(kesit):
    df = next(iter(kesit.values()))
    return df.index[-1] + pd.DateOffset(months=1)


class SahteForecaster:
    """TimesFM3Forecaster.predict sözleşmesini taklit eder.

    Medyan = son gözlem + adım (kesite duyarlı: son değer değişince çıktı da
    değişir); quantiles = (horizon, 9) — DEFAULT_QUANTILES düzeni, 0.1/0.5/0.9
    sütunları 0/4/8. Çağrılan horizon ve covariates kaydedilir.
    """

    def __init__(self):
        self.son_horizon = None
        self.son_covariates = "HIC"

    def predict(self, context, horizon, past_only_covariates=None, return_quantiles=False, **kw):
        assert return_quantiles, "bant için quantiles istenmeli"
        self.son_horizon = horizon
        self.son_covariates = past_only_covariates
        son = float(np.nan_to_num(context[-1]))
        adimlar = np.arange(1, horizon + 1, dtype=float)
        medyan = son + adimlar
        q = np.tile(DEFAULT_QUANTILES, (horizon, 1))  # (H, 9) sabit etiket matrisi
        # 0.1 / 0.5 / 0.9 sütunları medyanı izler; öbürleri simetrik dolgu.
        q[:, 0] = medyan - 2.0
        q[:, 4] = medyan
        q[:, 8] = medyan + 2.0
        return type("ForecastOutput", (), {"ts_id": None, "forecast": medyan, "quantiles": q})


def sahte_pipeline(monkeypatch):
    import trnowcast.models.tsfm_timesfm as mod

    fc = SahteForecaster()
    monkeypatch.setattr(mod, "_forecaster_yukle", lambda *a, **kw: fc)
    monkeypatch.setattr(mod, "_forecaster_cache", None)
    return fc


def suruculu_kesit(hedef_values):
    """Hedef + üç sürücü serisi (sürücüler hedef uzunluğunun 2 katı —
    hedefin başladığı aydan önce başlıyorlar, hizalama test edilecek)."""
    kesit = kesit_sozluk(hedef_values)
    hedef_idx = next(iter(kesit.values())).index
    genis_idx = pd.date_range("2016-01-01", periods=len(hedef_idx) + 30, freq="MS")
    for ad, taban in ((USD, 10.0), (BRENT, 60.0), (FAO, 100.0)):
        vals = [taban + i * 0.5 for i in range(len(genis_idx))]
        df = pd.DataFrame({"value": vals}, index=genis_idx)
        df.index.name = "ay"
        kesit[ad] = df
    return kesit


def agirlik_yerelde_mi(model_id: str) -> bool:
    # Ağ'sız kontrol: HF cache klasöründe snapshot var mı (indirme denemesi yok).
    try:
        from huggingface_hub import constants
    except ImportError:  # pragma: no cover
        return False
    cache = Path(constants.HF_HUB_CACHE) / ("models--" + model_id.replace("/", "--"))
    snapshots = cache / "snapshots"
    if not snapshots.is_dir():
        return False
    return any((s / "config.json").exists() for s in snapshots.iterdir())
