"""Chronos-2 zero-shot adapter (T15) birim testleri — offline (sahte pipeline).

Adapter motor kesiti sözlüğünü doğrudan alır ({seri_adı: ay-başı df}); registry/
parquet/alphağırlık gerekmez. Canlı ağırlıklı tek test `@pytest.mark.live` ve
"ağırlık HF cache'te varsa koş" kuralıyla (addopts zaten live'ı dışlar).

Review Focus 1: kesit kırpılınca tahmin değişmeli — kesitin gerçekten
kullanıldığının kanıtı; adapter ham store'a erişemez (imzası zaten kesit alır).
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trnowcast.backtest import ForecastPoint, ModelFailure
from trnowcast.models.tsfm_chronos import CHRONOS2_UNI, MIN_GOZLEM, MODEL_ADI

TUF = "turkiye_tufe_aylik_yuzde"


def kesit_sozluk(values, start="2018-01-01", seri=TUF):
    idx = pd.date_range(start, periods=len(values), freq="MS")
    df = pd.DataFrame({"value": [float(v) for v in values]}, index=idx)
    df.index.name = "ay"
    return {seri: df}


def sonraki_ay(kesit):
    df = next(iter(kesit.values()))
    return df.index[-1] + pd.DateOffset(months=1)


class SahtePipeline:
    """chronos Chronos2Pipeline.predict_df sözleşmesini taklit eder.

    Medyan = son gözlem + adım (kesite duyarlı: son değer değişince çıktı da
    değişir); bant = medyan ± 1. Çağrılan prediction_length kaydedilir.
    """

    def __init__(self):
        self.son_prediction_length = None

    def predict_df(self, df, prediction_length, quantile_levels, freq=None, **kw):
        assert freq == "MS", "aylık frekans açıkça verilmeli (frekans çıkarımına güvenme)"
        self.son_prediction_length = prediction_length
        son = float(df["target"].iloc[-1])
        adimlar = np.arange(1, prediction_length + 1, dtype=float)
        return pd.DataFrame(
            {
                "item_id": df["item_id"].iloc[0],
                "timestamp": pd.date_range(
                    df["timestamp"].iloc[-1] + pd.DateOffset(months=1),
                    periods=prediction_length,
                    freq="MS",
                ),
                "target_name": "target",
                "predictions": son + adimlar,
                "0.1": son + adimlar - 1.0,
                "0.5": son + adimlar,
                "0.9": son + adimlar + 1.0,
            }
        )


@pytest.fixture
def sahte(monkeypatch):
    import trnowcast.models.tsfm_chronos as mod

    pipe = SahtePipeline()
    monkeypatch.setattr(mod, "_pipeline_yukle", lambda *a, **kw: pipe)
    monkeypatch.setattr(mod, "_pipeline_cache", None)
    return pipe


# --- ModelFn sözleşmesi -------------------------------------------------------


def test_chronos2_uni_model_fn_sozlesmesi(sahte):
    kesit = kesit_sozluk([float(i) for i in range(36)])  # 2018-01 .. 2020-12
    hedef = sonraki_ay(kesit)  # 2021-01 → sahte medyan = 35 + 1 = 36
    fp = CHRONOS2_UNI(kesit, hedef, TUF)
    assert isinstance(fp, ForecastPoint)
    assert fp.model == MODEL_ADI == "chronos2_uni"
    assert fp.target_month == hedef
    assert fp.point == pytest.approx(36.0)
    assert fp.lower == pytest.approx(35.0)
    assert fp.upper == pytest.approx(37.0)
    assert fp.lower <= fp.point <= fp.upper


def test_chronos2_uni_cok_adim_ongoru(sahte):
    # Hedef son aydan 3 ay ileride: pipeline'a prediction_length=3 gitmeli,
    # nokta SON adımdan (medyan) alınmalı.
    kesit = kesit_sozluk([float(i) for i in range(36)])
    hedef = sonraki_ay(kesit) + pd.DateOffset(months=2)  # 2021-03
    fp = CHRONOS2_UNI(kesit, hedef, TUF)
    assert sahte.son_prediction_length == 3
    assert fp.target_month == hedef
    assert fp.point == pytest.approx(38.0)


def test_chronos2_uni_kesit_kirpilinca_tahmin_degisir(sahte):
    # Review Focus 1: yalnız kesitteki seri kullanılır — son ay kesitten
    # düşürülünce nokta tahmini DEĞİŞMELİ (kesit gerçekten okunuyor kanıtı).
    # Kusursuz çizgi serisinde adım artışı farkı kompanse edebileceğinden
    # gürültülü seri kullanılır: fake medyanı son gözlemi izler.
    gurultulu = [float(i) + (0.3 if i % 2 else -0.3) for i in range(36)]
    tam = kesit_sozluk(gurultulu)
    kirpik_df = next(iter(tam.values())).iloc[:-1]
    kirpik = {TUF: kirpik_df}
    hedef = sonraki_ay(tam)  # iki kesitte de aynı hedef ay
    fp_tam = CHRONOS2_UNI(tam, hedef, TUF)
    fp_kirpik = CHRONOS2_UNI(kirpik, hedef, TUF)
    assert fp_tam.point != fp_kirpik.point


def test_chronos2_uni_ay_boslugu_nan_ile_gecer(sahte):
    # Ay boşluğu değer uydurulmadan NaN ile kapatılır; chronos eksik bağlamı
    # kendi içinde maskeler (uydurma veri doldurma YASAK — Global Constraints).
    values = [float(i) for i in range(36)]
    idx = pd.date_range("2018-01-01", periods=36, freq="MS")
    df = pd.DataFrame({"value": values}, index=idx).drop(index=[idx[5]])
    kesit = {TUF: df}
    fp = CHRONOS2_UNI(kesit, sonraki_ay(kesit), TUF)
    assert fp.point == pytest.approx(36.0)


def test_chronos2_uni_min_gozlem_siniri_belgeli():
    # Plan: kısa kesitte (<24 gözlem) ModelFailure; sabit planla uyumlu.
    assert MIN_GOZLEM == 24


# --- ModelFailure yolları ------------------------------------------------------


def test_chronos2_uni_kisa_kesit_model_failure(sahte):
    kesit = kesit_sozluk([5.0] * (MIN_GOZLEM - 1))
    with pytest.raises(ModelFailure, match="yetersiz geçmiş"):
        CHRONOS2_UNI(kesit, sonraki_ay(kesit), TUF)


def test_chronos2_uni_hedef_seri_kesitte_yok_model_failure(sahte):
    kesit = kesit_sozluk([5.0] * 30)
    with pytest.raises(ModelFailure, match="kesitte yok"):
        CHRONOS2_UNI(kesit, sonraki_ay(kesit), "baska_seri")


def test_chronos2_uni_hedef_ay_kesitte_zaten_var_model_failure(sahte):
    kesit = kesit_sozluk([float(i) for i in range(36)])
    with pytest.raises(ModelFailure, match="zaten yayında"):
        CHRONOS2_UNI(kesit, pd.Timestamp("2020-06-01"), TUF)


def test_chronos2_uni_nan_cikti_model_failure(monkeypatch):
    # Pipeline NaN döndürürse sessiz NaN'lı ForecastPoint değil ModelFailure
    # (Faz 1 ders: motor FailedForecast sayabilsin).
    import trnowcast.models.tsfm_chronos as mod

    class NaNPipeline:
        def predict_df(self, df, prediction_length, quantile_levels, freq=None, **kw):
            n = prediction_length
            return pd.DataFrame(
                {
                    "item_id": "hedef",
                    "timestamp": pd.date_range("2021-01-01", periods=n, freq="MS"),
                    "target_name": "target",
                    "predictions": [np.nan] * n,
                    "0.1": [np.nan] * n,
                    "0.5": [np.nan] * n,
                    "0.9": [np.nan] * n,
                }
            )

    monkeypatch.setattr(mod, "_pipeline_yukle", lambda *a, **kw: NaNPipeline())
    monkeypatch.setattr(mod, "_pipeline_cache", None)
    kesit = kesit_sozluk([5.0] * 30)
    with pytest.raises(ModelFailure, match="NaN/inf"):
        CHRONOS2_UNI(kesit, sonraki_ay(kesit), TUF)


# --- Canlı test: ağırlık HF cache'te varsa koş, yoksa atla --------------------


def _agirlik_yerelde_mi(model_id: str) -> bool:
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


@pytest.mark.live
def test_chronos2_uni_live_tek_cikarim():
    if not _agirlik_yerelde_mi("amazon/chronos-2"):
        pytest.skip("chronos-2 ağırlığı HF cache'te yok — canlı test atlandı")
    # Bu test gerçek ağırlığı indirmez; HF hub'a çıkmayı da kapatarak yalnız
    # cache'ten yükler.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    kesit = kesit_sozluk([float(i) + (0.3 if i % 2 else -0.3) for i in range(40)])
    fp = CHRONOS2_UNI(kesit, sonraki_ay(kesit), TUF)
    assert np.isfinite(fp.point)
    assert fp.lower <= fp.point <= fp.upper
