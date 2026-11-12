"""TimesFM 3.0 adapter (T16) birim testleri — offline (sahte forecaster).

Adapter motor kesiti sözlüğünü doğrudan alır ({seri_adı: ay-başı df}); registry/
parquet/ağırlık gerekmez. Canlı ağırlıklı test test_tsfm_timesfm_live.py'de.

Review Focus 1: kesit kırpılınca tahmin değişmeli — kesitin gerçekten
kullanıldığının kanıtı; adapter ham store'a erişemez (imzası zaten kesit alır).
Review Focus 2: aylık seri uydurma doldurulmadan bağlam olur; kısa kesitte
adapter ModelFailure fırlatır (frekans yayma YASAK).
"""

import numpy as np
import pandas as pd
import pytest
from tsfm_timesfm_araclari import (
    BRENT,
    TUF,
    USD,
    kesit_sozluk,
    sahte_pipeline,
    sonraki_ay,
    suruculu_kesit,
)

from trnowcast.backtest import ForecastPoint, ModelFailure
from trnowcast.models.tsfm_timesfm import (
    DEFAULT_QUANTILES,
    MIN_GOZLEM,
    MODEL_ADI,
    TIMESFM3_MV,
)


@pytest.fixture
def sahte(monkeypatch):
    # Fixture araclari modülünde; yerel tanım ruff F811'i ve pytest fixture
    # keşfini birlikte çözer.
    return sahte_pipeline(monkeypatch)

# --- ModelFn sözleşmesi -------------------------------------------------------


def test_timesfm3_mv_model_fn_sozlesmesi(sahte):
    kesit = kesit_sozluk([float(i) for i in range(36)])  # 2018-01 .. 2020-12
    hedef = sonraki_ay(kesit)  # 2021-01 → sahte medyan = 35 + 1 = 36
    fp = TIMESFM3_MV(kesit, hedef, TUF)
    assert isinstance(fp, ForecastPoint)
    assert fp.model == MODEL_ADI == "timesfm3_mv"
    assert fp.target_month == hedef
    assert fp.point == pytest.approx(36.0)
    assert fp.lower == pytest.approx(34.0)
    assert fp.upper == pytest.approx(38.0)
    assert fp.lower <= fp.point <= fp.upper


def test_timesfm3_mv_cok_adim_ongoru(sahte):
    # Hedef son aydan 3 ay ileride: predict'e horizon=3 gitmeli, nokta SON
    # adımdan (medyan) alınmalı.
    kesit = kesit_sozluk([float(i) for i in range(36)])
    hedef = sonraki_ay(kesit) + pd.DateOffset(months=2)  # 2021-03
    fp = TIMESFM3_MV(kesit, hedef, TUF)
    assert sahte.son_horizon == 3
    assert fp.target_month == hedef
    assert fp.point == pytest.approx(38.0)


def test_timesfm3_mv_surucu_kovaryati_gecer(sahte):
    # Çok değişkenli çağrı: sürücüler past_only_covariates olarak geçmeli;
    # satır sayısı = sürücü sayısı, genişlik = hedef bağlam uzunluğu
    # (sürücü hedeften uzun olsa bile hedef indeksine KESİLMELİ).
    kesit = suruculu_kesit([float(i) for i in range(36)])
    hedef = sonraki_ay(kesit)
    TIMESFM3_MV(kesit, hedef, TUF)
    cov = sahte.son_covariates
    assert isinstance(cov, np.ndarray), "sürücü kovaryatı dizi olarak geçmeli"
    assert cov.shape == (3, 36)


def test_timesfm3_mv_surucu_hizalamasi(sahte):
    # Sürücü satırı hedef bağlamıyla ay hizalı olmalı: hedefin son bağlam ayı
    # 2020-12, sürücünün oradaki değeri 10 + i*0.5 (2016-01 başlangıç) →
    # i = 59, değer = 39.5. Yanlış hizalama bu testi bozar.
    kesit = suruculu_kesit([float(i) for i in range(36)])
    TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    cov = sahte.son_covariates
    assert cov[0, -1] == pytest.approx(10.0 + 59 * 0.5)


def test_timesfm3_mv_surucusuz_graceful(sahte):
    # Kesitte hiç sürücü yok: yalnız hedef seriyle çalışır (graceful),
    # covariates None geçer.
    kesit = kesit_sozluk([float(i) for i in range(36)])
    fp = TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    assert sahte.son_covariates is None
    assert fp.point == pytest.approx(36.0)


def test_timesfm3_mv_eksik_surucu_atlanir(sahte):
    # Sürücülerden biri kesitte yoksa o satır atlanır, öbürleri geçer.
    kesit = suruculu_kesit([float(i) for i in range(36)])
    del kesit[BRENT]
    TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    cov = sahte.son_covariates
    assert cov.shape == (2, 36)


def test_timesfm3_mv_surucu_bosugu_nan_kalir(sahte):
    # Sürücüde ay boşluğu uydurma doldurulmaz: NaN model'e öyle gider
    # (TimesFM iç lineer interpolasyonu modelin kendi ön işlemesidir,
    # adapter veri üretmez — Global Constraints).
    kesit = suruculu_kesit([float(i) for i in range(36)])
    kesit[USD] = kesit[USD].drop(index=pd.Timestamp("2019-03-01"))
    TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    cov = sahte.son_covariates
    # Hedef bağlamındaki 2019-03 satırı NaN kalmalı.
    i_nan = list(kesit[TUF].index).index(pd.Timestamp("2019-03-01"))
    assert np.isnan(cov[0, i_nan])


def test_timesfm3_mv_kesit_kirpilinca_tahmin_degisir(sahte):
    # Review Focus 1: yalnız kesitteki seri kullanılır — son ay kesitten
    # düşürülünce nokta tahmini DEĞİŞMELİ (kesit gerçekten okunuyor kanıtı).
    gurultulu = [float(i) + (0.3 if i % 2 else -0.3) for i in range(36)]
    tam = kesit_sozluk(gurultulu)
    kirpik_df = next(iter(tam.values())).iloc[:-1]
    kirpik = {TUF: kirpik_df}
    hedef = sonraki_ay(tam)  # iki kesitte de aynı hedef ay
    fp_tam = TIMESFM3_MV(tam, hedef, TUF)
    fp_kirpik = TIMESFM3_MV(kirpik, hedef, TUF)
    assert fp_tam.point != fp_kirpik.point


def test_timesfm3_mv_ay_boslugu_nan_ile_gecer(sahte):
    # Hedef seride ay boşluğu değer uydurulmadan NaN ile bağlama gider;
    # TimesFM iç interpolasyonu maskeler (uydurma veri doldurma YASAK).
    values = [float(i) for i in range(36)]
    idx = pd.date_range("2018-01-01", periods=36, freq="MS")
    df = pd.DataFrame({"value": values}, index=idx).drop(index=[idx[5]])
    kesit = {TUF: df}
    fp = TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    assert fp.point == pytest.approx(36.0)


# --- Sabit belgeleri ----------------------------------------------------------


def test_timesfm3_mv_min_gozlem_siniri_belgeli():
    # Plan Review Focus 2: kısa kesitte ModelFailure; frekans yayma ile
    # bağlam uydurma YOK — 24 Chronos ile aynı taban.
    assert MIN_GOZLEM == 24


def test_timesfm3_mv_default_quantiles_dokumani():
    # %80 bant = 0.1/0.9; DEFAULT_QUANTILES TimesFM 3.0 ModelConfig düzeni.
    assert DEFAULT_QUANTILES[0] == pytest.approx(0.1)
    assert DEFAULT_QUANTILES[4] == pytest.approx(0.5)
    assert DEFAULT_QUANTILES[8] == pytest.approx(0.9)


# --- ModelFailure yolları ------------------------------------------------------


def test_timesfm3_mv_kisa_kesit_model_failure(sahte):
    kesit = kesit_sozluk([5.0] * (MIN_GOZLEM - 1))
    with pytest.raises(ModelFailure, match="yetersiz geçmiş"):
        TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)


def test_timesfm3_mv_hedef_seri_kesitte_yok_model_failure(sahte):
    kesit = kesit_sozluk([5.0] * 30)
    with pytest.raises(ModelFailure, match="kesitte yok"):
        TIMESFM3_MV(kesit, sonraki_ay(kesit), "baska_seri")


def test_timesfm3_mv_hedef_ay_kesitte_zaten_var_model_failure(sahte):
    kesit = kesit_sozluk([float(i) for i in range(36)])
    with pytest.raises(ModelFailure, match="zaten yayında"):
        TIMESFM3_MV(kesit, pd.Timestamp("2020-06-01"), TUF)


def test_timesfm3_mv_nan_cikti_model_failure(monkeypatch):
    # Forecaster NaN döndürürse sessiz NaN'lı ForecastPoint değil ModelFailure.
    import trnowcast.models.tsfm_timesfm as mod

    class NaNForecaster:
        def predict(self, context, horizon, past_only_covariates=None, return_quantiles=False, **kw):
            n = horizon
            return type(
                "ForecastOutput",
                (),
                {
                    "ts_id": None,
                    "forecast": np.full(n, np.nan),
                    "quantiles": np.full((n, 9), np.nan),
                },
            )

    monkeypatch.setattr(mod, "_forecaster_yukle", lambda *a, **kw: NaNForecaster())
    monkeypatch.setattr(mod, "_forecaster_cache", None)
    kesit = kesit_sozluk([5.0] * 30)
    with pytest.raises(ModelFailure, match="NaN/inf"):
        TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)


def test_timesfm3_mv_predict_hatasi_model_failure(sahte, monkeypatch):
    # predict'ten çıkan beklenmedik hata ModelFailure'e sarılır (motor
    # o (model, ay) satırını NaN ile yazar, çökmez) — TEK AYLIK arıza.
    def bozuk_predict(*a, **kw):
        raise RuntimeError("çıkarsama sırasında hata")

    fc = sahte_pipeline(monkeypatch)
    monkeypatch.setattr(fc, "predict", bozuk_predict)
    kesit = kesit_sozluk([5.0] * 30)
    with pytest.raises(ModelFailure, match="çıkarsama sırasında hata"):
        TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)


def test_timesfm3_mv_yukleme_hatasi_model_failure_olmaz(monkeypatch):
    # Denetçi bulgusu: ağırlık/CUDA yükleme SİSTEMATİK hatadır; ModelFailure'e
    # sarılırsa motor (backtest.py:134) her ay sessiz NaN yazar ve kalıcı
    # arıza tek-aylık başarısızlıktan ayırt edilmez. Yükleme hatası olduğu
    # gibi YÜKSELMELİ — çökme görünür, sessiz sütun yok.
    import trnowcast.models.tsfm_timesfm as mod

    def bozuk_yukle(*a, **kw):
        raise RuntimeError("ağırlık bozuk / CUDA sürücüsü yok")

    monkeypatch.setattr(mod, "_forecaster_yukle", bozuk_yukle)
    monkeypatch.setattr(mod, "_forecaster_cache", None)
    kesit = kesit_sozluk([5.0] * 30)
    with pytest.raises(RuntimeError, match="ağırlık bozuk"):
        TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    # Hata ModelFailure türevi OLMAMALI — motor bunu yutup NaN yazmasın.
    with pytest.raises(Exception) as bilgi:
        TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    assert not isinstance(bilgi.value, ModelFailure)
