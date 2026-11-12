"""Klasik benchmark modelleri (T13) birim testleri — tamamen offline.

Modeller motor kesiti sözlüğünü doğrudan alır ({seri_adı: ay-başı indeksli df});
registry/parquet gerekmez. Review Focus 4: tekil-sabit seri ARIMA'da ModelFailure.
"""

import warnings
from typing import ClassVar

import pandas as pd
import pytest
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from trnowcast.backtest import ForecastPoint, ModelFailure
from trnowcast.models import MODELS, classic
from trnowcast.models.baseline import naive, seasonal_naive
from trnowcast.models.classic import arima, ets

TUF = "turkiye_tufe_aylik_yuzde"


def kesit_sozluk(values, start="2018-01-01", seri=TUF):
    idx = pd.date_range(start, periods=len(values), freq="MS")
    df = pd.DataFrame({"value": [float(v) for v in values]}, index=idx)
    df.index.name = "ay"
    return {seri: df}


def sonraki_ay(kesit):
    df = next(iter(kesit.values()))
    return df.index[-1] + pd.DateOffset(months=1)


# --- MODELS sözlüğü ---------------------------------------------------------


def test_models_sekiz_anahtar():
    # T19: klasik dörtlü + T15-T18'in dört yeni yarışmacısı.
    assert set(MODELS) == {
        "naive",
        "seasonal_naive",
        "arima",
        "ets",
        "chronos2_uni",
        "timesfm3_mv",
        "bridge",
        "anket_pka",
    }


def test_models_varsayilan_hedef_seriyle_calisir():
    # MODELS girdileri ModelFn imzasında: (kesit, hedef_ay) — hedef seri varsayılan.
    kesit = kesit_sozluk([5.0] * 24)
    fp = MODELS["naive"](kesit, sonraki_ay(kesit))
    assert fp.point == pytest.approx(5.0)


# --- naive -------------------------------------------------------------------


def test_naive_sabit_seri_nokta_ve_bant_tabani():
    # Sabit seri: eğitim hataları 0 → bant tabana (0.2) oturur.
    kesit = kesit_sozluk([5.0] * 24)
    fp = naive(kesit, sonraki_ay(kesit), target=TUF)
    assert isinstance(fp, ForecastPoint)
    assert fp.point == pytest.approx(5.0)
    assert fp.lower == pytest.approx(4.8)
    assert fp.upper == pytest.approx(5.2)


def test_naive_bant_egitim_hatasi_persentili():
    # Her adım +2: |hata| persentili 2.0 → bant 2.0 (tabandan büyük).
    kesit = kesit_sozluk([1.0 + 2.0 * i for i in range(24)])
    fp = naive(kesit, sonraki_ay(kesit), target=TUF)
    assert fp.point == pytest.approx(47.0)
    assert fp.lower == pytest.approx(45.0)
    assert fp.upper == pytest.approx(49.0)


def test_naive_yetersiz_gecmis_model_failure():
    kesit = kesit_sozluk([5.0] * 23)
    with pytest.raises(ModelFailure, match="yetersiz geçmiş"):
        naive(kesit, sonraki_ay(kesit), target=TUF)


def test_naive_nan_son_deger_model_failure():
    # Sessiz NaN'lı ForecastPoint yerine FailedForecast: motor sayabilsin.
    kesit = kesit_sozluk([5.0] * 23 + [float("nan")])
    with pytest.raises(ModelFailure, match="NaN"):
        naive(kesit, sonraki_ay(kesit), target=TUF)


# --- seasonal_naive ----------------------------------------------------------


def test_seasonal_naive_nokta_oniki_ay_once():
    # Değerler 0..29 (2018-01..2020-06); hedef 2020-07 → kaynak 2019-07 = 18.0.
    kesit = kesit_sozluk(list(range(30)))
    hedef = pd.Timestamp("2020-07-01")
    fp = seasonal_naive(kesit, hedef, target=TUF)
    assert fp.point == pytest.approx(18.0)
    # Mevsimsel |hata| hepsi 12.0 → bant 12.0.
    assert fp.lower == pytest.approx(6.0)
    assert fp.upper == pytest.approx(30.0)


def test_seasonal_naive_kaynak_ay_kesitte_yok_model_failure():
    kesit = kesit_sozluk(list(range(30)))  # 2018-01 .. 2020-06
    # Hedef 2021-07 → kaynak 2020-07 kesitte yok (seri 2020-06'da bitiyor).
    with pytest.raises(ModelFailure):
        seasonal_naive(kesit, pd.Timestamp("2021-07-01"), target=TUF)


def test_seasonal_naive_yetersiz_gecmis_model_failure():
    kesit = kesit_sozluk(list(range(23)))
    with pytest.raises(ModelFailure, match="yetersiz geçmiş"):
        seasonal_naive(kesit, sonraki_ay(kesit), target=TUF)


def test_seasonal_naive_nan_kaynak_deger_model_failure():
    values = [float(i) for i in range(30)]  # 2018-01 .. 2020-06
    values[18] = float("nan")  # kaynak ay 2019-07
    kesit = kesit_sozluk(values)
    with pytest.raises(ModelFailure, match="NaN"):
        seasonal_naive(kesit, pd.Timestamp("2020-07-01"), target=TUF)


# --- arima / ets: sentetik trend ---------------------------------------------


TREND = list(range(48))  # eğim 1 olan kusursuz trend: 2017-01 .. 2020-12


def test_arima_trend_seri_nokta_tahmini():
    kesit = kesit_sozluk(TREND, start="2017-01-01")
    hedef = sonraki_ay(kesit)  # 2021-01 → beklenen ≈ 48
    fp = arima(kesit, hedef, target=TUF)
    assert fp.point == pytest.approx(48.0, abs=3.0)
    assert fp.lower <= fp.point <= fp.upper
    # Bant gerçek: üst > alt (dejenere sıfır bant değil).
    assert fp.upper > fp.lower


def test_ets_trend_seri_nokta_tahmini():
    # Kusursuz trendde kalıntı std'si 0 çıkar; bant testi için deterministik
    # küçük gürültü eklenir (dönüşümlü ±0.5) — nokta tahmini yine trendi izler.
    gurultulu = [v + (0.5 if i % 2 else -0.5) for i, v in enumerate(TREND)]
    kesit = kesit_sozluk(gurultulu, start="2017-01-01")
    hedef = sonraki_ay(kesit)
    fp = ets(kesit, hedef, target=TUF)
    assert fp.point == pytest.approx(48.0, abs=3.0)
    assert fp.lower < fp.point < fp.upper


# --- Review Focus 4: tekil-sabit seri → ModelFailure -------------------------


def test_arima_sabit_seri_model_failure():
    # Tekil seri: bant/CI tanımsız → sessiz 0 değil, FailedForecast (ModelFailure).
    kesit = kesit_sozluk([3.0] * 30)
    with pytest.raises(ModelFailure):
        arima(kesit, sonraki_ay(kesit), target=TUF)


def test_ets_sabit_seri_model_failure():
    kesit = kesit_sozluk([3.0] * 30)
    with pytest.raises(ModelFailure):
        ets(kesit, sonraki_ay(kesit), target=TUF)


def test_arima_hedef_ay_kesitte_zaten_var_model_failure():
    # Hedef ay kesit tarihi açısından gelecekte olmalı; aksi halde adım tanımsız.
    kesit = kesit_sozluk(TREND, start="2017-01-01")
    with pytest.raises(ModelFailure):
        arima(kesit, pd.Timestamp("2020-06-01"), target=TUF)


# --- Yakınsama: statsmodels exception fırlatmaz, ConvergenceWarning basar ----


class YakinsamayanSonuc:
    """statsmodels davranışı: yakınsamayan fit sonlu çıktıya rağmen döner."""

    mle_retvals: ClassVar[dict] = {"converged": False}


def test_arima_yakinsamayan_fit_model_failure(monkeypatch):
    class YakinsamayanARIMA:
        def __init__(self, *args, **kwargs): ...
        def fit(self):
            return YakinsamayanSonuc()  # get_forecast'a hiç gelinmemeli

    monkeypatch.setattr(classic, "ARIMA", YakinsamayanARIMA)
    kesit = kesit_sozluk(TREND, start="2017-01-01")
    with pytest.raises(ModelFailure, match="yakınsamadı"):
        classic.arima(kesit, sonraki_ay(kesit), target=TUF)


def test_ets_yakinsamayan_fit_model_failure(monkeypatch):
    class YakinsamayanETS:
        def __init__(self, *args, **kwargs): ...
        def fit(self, **kwargs):
            return YakinsamayanSonuc()

    monkeypatch.setattr(classic, "ExponentialSmoothing", YakinsamayanETS)
    kesit = kesit_sozluk(TREND, start="2017-01-01")
    with pytest.raises(ModelFailure, match="yakınsamadı"):
        classic.ets(kesit, sonraki_ay(kesit), target=TUF)


def test_arima_convergence_warning_model_failure(monkeypatch):
    # Yalnız mle_retvals bayrağı değil: ConvergenceWarning basan fit de başarısız.
    class UyaranARIMA:
        def __init__(self, *args, **kwargs): ...
        def fit(self):
            warnings.warn("optimizer yakınsamadı", ConvergenceWarning)
            raise AssertionError("warning error'a dönüşmeliydi")

    monkeypatch.setattr(classic, "ARIMA", UyaranARIMA)
    kesit = kesit_sozluk(TREND, start="2017-01-01")
    with pytest.raises(ModelFailure, match="yakınsama"):
        classic.arima(kesit, sonraki_ay(kesit), target=TUF)
