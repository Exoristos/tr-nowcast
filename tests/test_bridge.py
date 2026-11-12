"""Bridge / MIDAS-lite model (T17) birim testleri — offline, sentetik kesit.

Adapter motor kesiti sözlüğünü doğrudan alır ({seri_adı: ay-başı df}); registry/
parquet/sklearn dışı bağımlılık gerekmez.

Review Focus 4: gecikme ladder yalnız t <= hedef-1 sürücü değerlerini kullanır;
sürücünün hedef ay ve sonrasındaki değeri değişince tahmin DEĞİŞMEZ. Bu test
sızıntı yapan (driver(t) okuyan) bir uygulamada başarısız olur — geçmesi
sızıntı yokluğunun kanıtıdır.
"""

import numpy as np
import pandas as pd
import pytest

from trnowcast.backtest import ForecastPoint, ModelFailure
from trnowcast.models.bridge import BANT_MIN, MIN_EGITIM_SATIRI, MODEL_ADI, SURUCULER

TUF = "turkiye_tufe_aylik_yuzde"
USD = "usd_try_gunluk"
BRENT = "brent_gunluk"
FAO = "fao_gida_endeks"


def _df(values, index):
    df = pd.DataFrame({"value": np.asarray(values, dtype=float)}, index=index)
    df.index.name = "ay"
    return df


def kesit_kur(n=72, bas="2015-01-01", suruculer=(USD, BRENT, FAO)):
    """Sentetik kesit: target(t) = 0.5*usd(t-1) + 2.0 + gürültü.

    Sürücüler bağımsız üretilir; hedef seri kesit sürücülerinden 1 ay gecikmeli
    kurulur — ridge bu ilişkiyi öğrenebilmeli. Dönen sözlükte beklenen koşullu
    ortalama da taşınır (anahtar: _BEKLENEN).
    """
    idx = pd.date_range(bas, periods=n, freq="MS")
    rng = np.random.default_rng(42)
    usd = 10.0 + 0.1 * np.arange(n) + rng.normal(0, 0.5, n)
    brent = 60.0 + 5.0 * np.sin(np.arange(n) / 6.0)
    fao = 100.0 + 3.0 * np.cos(np.arange(n) / 4.0)
    eps = rng.normal(0, 0.3, n)
    target = 0.5 * np.roll(usd, 1) + 2.0 + eps
    target[0] = 20.0  # roll'un sardığı ilk değer yerine sabit başlangıç
    kesit = {TUF: _df(target, idx)}
    seriler = {USD: usd, BRENT: brent, FAO: fao}
    for ad in suruculer:
        kesit[ad] = _df(seriler[ad], idx)
    return kesit


def gelecek_ekle(kesit, ad, n_ay, deger):
    """Sürücü df'ini kesit sonrası aylarla uzatır (gelecek değer sahte)."""
    df = kesit[ad]
    idx = pd.date_range(df.index[-1] + pd.DateOffset(months=1), periods=n_ay, freq="MS")
    kesit[ad] = pd.concat([df, _df(np.full(n_ay, deger), idx)])


def hedef_ayi(kesit):
    return kesit[TUF].index[-1] + pd.DateOffset(months=1)


def BRIDGE_CAGIR(kesit):
    from trnowcast.models.bridge import BRIDGE

    return BRIDGE(kesit, hedef_ayi(kesit), TUF)


def beklenen_ortalama(kesit):
    """target(hedef) = 0.5*usd(hedef-1) + 2.0 (sentetik üretim ilişkisi)."""
    return 0.5 * float(kesit[USD]["value"].iloc[-1]) + 2.0


# --- ModelFn sözleşmesi -------------------------------------------------------


def test_bridge_model_fn_sozlesmesi():
    kesit = kesit_kur()
    fp = BRIDGE_CAGIR(kesit)
    assert isinstance(fp, ForecastPoint)
    assert fp.model == MODEL_ADI == "bridge"
    assert fp.target_month == hedef_ayi(kesit)
    assert np.isfinite(fp.point)
    assert fp.lower <= fp.point <= fp.upper
    assert fp.upper - fp.point >= BANT_MIN
    assert fp.point - fp.lower >= BANT_MIN


def test_bridge_sabitler_plana_uyumlu():
    # Plan: eğitim satırı < 36 → ModelFailure; bant min 0.2; sürücü üçlüsü.
    assert MIN_EGITIM_SATIRI == 36
    assert BANT_MIN == 0.2
    assert set(SURUCULER) == {USD, BRENT, FAO}


# --- Öğrenme: katsayılar ve makul bant ---------------------------------------


def test_bridge_katsayilar_ogrenilir_nokta_makul():
    # target = 0.5*usd(t-1) + 2 + gürültü; ridge nokta tahmini koşullu ortalama
    # civarına oturmalı (gürültü std 0.3 → tolerans 0.5), bant gürültü
    # persentilinde ama 0.2 tabanının üstünde kalmalı.
    kesit = kesit_kur()
    fp = BRIDGE_CAGIR(kesit)
    beklenen = beklenen_ortalama(kesit)
    assert abs(fp.point - beklenen) < 0.5
    assert 0.2 <= fp.point - fp.lower <= 1.5


def test_bridge_surucu_degeri_tahmini_etkiler():
    # Sürücü gerçekten kullanılıyor: yalnız usd'nin son (hedef-1) değeri
    # değişince nokta tahmin DEĞİŞMELİ (gelecek değil, meşru son gözlem).
    kesit1 = kesit_kur()
    kesit2 = kesit_kur()
    df = kesit2[USD].copy()
    df.iloc[-1, df.columns.get_loc("value")] = float(df["value"].iloc[-1]) + 5.0
    kesit2[USD] = df
    fp1 = BRIDGE_CAGIR(kesit1)
    fp2 = BRIDGE_CAGIR(kesit2)
    assert fp1.point != fp2.point


def test_bridge_bant_gurultusuz_seride_tabana_oturur():
    # Gürültü yok: artıklar ~0 → bant 0.2 tabanına oturur (min 0.2 kuralı).
    n = 60
    idx = pd.date_range("2015-01-01", periods=n, freq="MS")
    usd = 10.0 + 0.1 * np.arange(n)
    target = 0.5 * np.concatenate([[usd[0]], usd[:-1]]) + 2.0
    kesit = {TUF: _df(target, idx), USD: _df(usd, idx)}
    fp = BRIDGE_CAGIR(kesit)
    assert fp.point - fp.lower == pytest.approx(BANT_MIN)


# --- Review Focus 4: gelecek-değişim sızıntı testi ----------------------------


def test_bridge_surucu_gelecek_degeri_tahmini_degistirmez():
    # Sürücü df'ine hedef ay ve sonrası sahte değerler eklenir; bu gelecek
    # değerler değişince tahmin BİTİŞİK AYNI kalmalı. Sızıntı yapan (driver(t)
    # okuyan) uygulamada bu test başarısız olur.
    kesit1 = kesit_kur()
    kesit2 = kesit_kur()
    for ad in (USD, BRENT, FAO):
        gelecek_ekle(kesit1, ad, 2, 100.0)
        gelecek_ekle(kesit2, ad, 2, 999.0)
    fp1 = BRIDGE_CAGIR(kesit1)
    fp2 = BRIDGE_CAGIR(kesit2)
    assert fp1.point == fp2.point
    assert fp1.lower == fp2.lower
    assert fp1.upper == fp2.upper


# --- Eksik sürücü: sütun atlanır, model çalışır --------------------------------


def test_bridge_eksik_surucu_ile_calisir():
    # Yalnız usd var: brent/fao sütunları atlanır, model yine tahmin üretir.
    kesit = kesit_kur(suruculer=(USD,))
    fp = BRIDGE_CAGIR(kesit)
    assert abs(fp.point - beklenen_ortalama(kesit)) < 0.5


def test_bridge_hic_surucu_yok_ile_calisir():
    # Sürücü hiç yok: hedef 1/2/3 gecikme + sabit → AR(3) bridge.
    kesit = kesit_kur(suruculer=())
    fp = BRIDGE_CAGIR(kesit)
    assert isinstance(fp, ForecastPoint)
    assert np.isfinite(fp.point)


def test_bridge_surucu_son_ayi_eksikse_sutun_atlanir():
    # brent kesitte var ama hedef-1 ayında değeri yok → o sütun atlanır,
    # model çökmez (graceful).
    kesit = kesit_kur()
    kesit[BRENT] = kesit[BRENT].iloc[:-1]
    fp = BRIDGE_CAGIR(kesit)
    assert isinstance(fp, ForecastPoint)


# --- ModelFailure yolları ------------------------------------------------------


def test_bridge_kisa_kesit_model_failure():
    # n=38 → eğitim satırı 38-3=35 < 36 → ModelFailure.
    kesit = kesit_kur(n=38)
    with pytest.raises(ModelFailure, match="eğitim satırı"):
        BRIDGE_CAGIR(kesit)


def test_bridge_esik_ustu_kesit_calisir():
    # n=39 → eğitim satırı tam 36 → sınır üstü, çalışır.
    kesit = kesit_kur(n=39)
    fp = BRIDGE_CAGIR(kesit)
    assert isinstance(fp, ForecastPoint)


def test_bridge_hedef_seri_kesitte_yok_model_failure():
    kesit = kesit_kur()
    with pytest.raises(ModelFailure, match="kesitte yok"):
        BRIDGE_CAGIR_YOK(kesit)


def BRIDGE_CAGIR_YOK(kesit):
    from trnowcast.models.bridge import BRIDGE

    BRIDGE(kesit, hedef_ayi(kesit), "baska_seri")


def test_bridge_hedef_ay_kesitte_zaten_var_model_failure():
    kesit = kesit_kur()
    with pytest.raises(ModelFailure, match="tek adım"):
        BRIDGE_CAGIR_AY(kesit, kesit[TUF].index[-1])


def test_bridge_cok_adimli_hedef_model_failure():
    # Plan: nokta = TEK adım öngörü; hedef ay kesitten 2+ ay ilerideyse
    # uydurma zincirleme tahmin yerine ModelFailure.
    kesit = kesit_kur()
    with pytest.raises(ModelFailure, match="tek adım"):
        BRIDGE_CAGIR_AY(kesit, hedef_ayi(kesit) + pd.DateOffset(months=1))


def BRIDGE_CAGIR_AY(kesit, ay):
    from trnowcast.models.bridge import BRIDGE

    return BRIDGE(kesit, ay, TUF)


def test_bridge_hedef_gecikme_degeri_eksik_model_failure():
    # Hedef seride hedef-2 ayı yok: gecikme satırı kurulamaz → sessiz NaN
    # değil ModelFailure (Faz 1 ders).
    kesit = kesit_kur()
    df = kesit[TUF].drop(index=kesit[TUF].index[-2])
    kesit[TUF] = df
    with pytest.raises(ModelFailure, match="gecikme"):
        BRIDGE_CAGIR(kesit)
