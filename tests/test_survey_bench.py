"""TCMB PKA anket benchmark'ı (T18) birim testleri — offline (sentetik kesit).

Adapter motor kesit sözlüğünü alır ({seri_adı: ay-başı df}); registry/parquet/
EVDS gerekmez. Review Focus 5: hizalama tablosu testlidir — hedef ay M için
M anket satırı kullanılır; M satırı yoksa ModelFailure, yanlış ay sessizce
kullanılmaz.
"""

import numpy as np
import pandas as pd
import pytest

from trnowcast import store
from trnowcast.backtest import (
    CUTOFF_OFFSET_DAYS,
    ForecastPoint,
    ModelFailure,
    asof_monthly,
    run_backtest,
)
from trnowcast.models.survey_bench import ANKET_PKA, ANKET_SERISI, BANT_TABANI, MODEL_ADI
from trnowcast.store import SeriesMeta, save_series

TUF = "turkiye_tufe_aylik_yuzde"
# Motor-entegrasyon testlerindeki hedef seri adı.
HEDEF = "sahte_tufe_anket"


def aylık_df(values, start="2023-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="MS")
    df = pd.DataFrame({"value": [float(v) for v in values]}, index=idx)
    df.index.name = "ay"
    return df


def kesit(anket_values, hedef_values, anket_start="2023-01-01", hedef_start="2023-01-01"):
    """Anket ve hedef serisi kesiti; anketin hedef ayı kapsayacak kadar uzun olduğu varsayılır."""
    return {
        ANKET_SERISI: aylık_df(anket_values, anket_start),
        TUF: aylık_df(hedef_values, hedef_start),
    }


# Anket değerleri aydan aya farklı: hizalama hatası yakalansın diye.
ANKET_DEGERLERI = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]


# --- ModelFn sözleşmesi + Review Focus 5 hizalama ------------------------------


def test_anket_pka_model_fn_sozlesmesi():
    k = kesit(ANKET_DEGERLERI, [2.0] * 11)
    hedef_ay = pd.Timestamp("2023-06-01")  # hedef M → anket M (2023-06)
    fp = ANKET_PKA(k, hedef_ay, TUF)
    assert isinstance(fp, ForecastPoint)
    assert fp.model == MODEL_ADI == "anket_pka"
    assert fp.target_month == hedef_ay
    # Nokta = M AYININ anket değeri (6.0); ilk/son satır değil.
    assert fp.point == pytest.approx(6.0)
    assert fp.lower <= fp.point <= fp.upper


def test_hizalama_tablosu_tum_aylar():
    # Hizalama tablosu: her hedef ay M için nokta = anket satırı M.
    k = kesit(ANKET_DEGERLERI, [2.0] * 11)
    for i, beklenen in enumerate(ANKET_DEGERLERI[:11], start=1):
        hedef_ay = pd.Timestamp("2023-01-01") + pd.DateOffset(months=i - 1)
        fp = ANKET_PKA(k, hedef_ay, TUF)
        assert fp.point == pytest.approx(beklenen), f"{hedef_ay:%Y-%m} satırı eşleşmedi"


def test_anket_komsu_ay_satiri_kullanilmaz():
    # Hedef M'nin anketi yoksa sonraki/önceki ayın satırı sessizce kullanılmaz:
    # motor lag 0 ile M anketini kesitte verir; M yoksa bu ModelFailure'dır.
    k = kesit(ANKET_DEGERLERI, [2.0] * 11)
    # 2023-06 satırını düşür → hedef 2023-06 anketsiz kalır.
    df = k[ANKET_SERISI].drop(index=pd.Timestamp("2023-06-01"))
    k = {ANKET_SERISI: df, TUF: k[TUF]}
    with pytest.raises(ModelFailure, match="2023-06"):
        ANKET_PKA(k, pd.Timestamp("2023-06-01"), TUF)


# --- Bant: tarihsel |gerçek−anket| %80 persentili, taban 0.2 --------------------


def test_bant_hesabi_persentil():
    # Hedef gerçekleri anketten bilinen sapmalarla: |hata|'ların %80 persentili.
    sapmalar = [0.1, 0.4, 0.2, 0.9, 0.3, 0.5, 0.7, 0.2, 0.6, 0.1, 0.8]
    anket = ANKET_DEGERLERI
    hedef_gercek = [a + s for a, s in zip(anket[:11], sapmalar, strict=True)]
    # Hedef ay 2023-12: hedef serisi kesitte 2023-11'e kadar (gerçek lag'i temsil eder).
    k = kesit(anket, hedef_gercek)
    fp = ANKET_PKA(k, pd.Timestamp("2023-12-01"), TUF)
    hatalar = np.abs(np.array(hedef_gercek) - np.array(anket[:11]))
    beklenen_bant = max(float(np.percentile(hatalar, 80)), BANT_TABANI)
    assert fp.point == pytest.approx(anket[11])
    assert fp.lower == pytest.approx(fp.point - beklenen_bant)
    assert fp.upper == pytest.approx(fp.point + beklenen_bant)


def test_bant_tabani_02():
    # Hatalar hep küçükse bant tabana (0.2) yükseltilir.
    anket = ANKET_DEGERLERI
    hedef_gercek = [a + 0.01 * (i + 1) for i, a in enumerate(anket[:11])]
    k = kesit(anket, hedef_gercek)
    fp = ANKET_PKA(k, pd.Timestamp("2023-12-01"), TUF)
    assert fp.lower == pytest.approx(fp.point - 0.2)
    assert fp.upper == pytest.approx(fp.point + 0.2)


# --- ModelFailure yolları -------------------------------------------------------


def test_anket_ayi_hedef_aydan_sonra_model_failure():
    # Anket kesiti hedef ayı kapsamıyorsa (M anket satırı yok) ModelFailure.
    k = kesit(ANKET_DEGERLERI, [2.0] * 11)
    with pytest.raises(ModelFailure, match="2024-01"):
        ANKET_PKA(k, pd.Timestamp("2024-01-01"), TUF)


def test_anket_serisi_kesitte_yok_model_failure():
    k = {TUF: aylık_df([2.0] * 11)}
    with pytest.raises(ModelFailure, match="kesitte yok"):
        ANKET_PKA(k, pd.Timestamp("2023-06-01"), TUF)


def test_hedef_seri_kesitte_yok_model_failure():
    k = {ANKET_SERISI: aylık_df(ANKET_DEGERLERI)}
    with pytest.raises(ModelFailure, match="kesitte yok"):
        ANKET_PKA(k, pd.Timestamp("2023-06-01"), TUF)


def test_anket_degeri_nan_model_failure():
    values = list(ANKET_DEGERLERI)
    values[5] = np.nan
    k = kesit(values, [2.0] * 11)
    with pytest.raises(ModelFailure, match="NaN/inf"):
        ANKET_PKA(k, pd.Timestamp("2023-06-01"), TUF)


def test_bant_ortusme_bos_model_failure():
    # Hedef ve anket kesitleri hiç kesişmiyorsa tarihsel hata yok → ModelFailure
    # (sessiz 0.2 bant uydurulmaz).
    k = {
        ANKET_SERISI: aylık_df(ANKET_DEGERLERI, start="2023-01-01"),
        TUF: aylık_df([2.0] * 6, start="2025-01-01"),
    }
    with pytest.raises(ModelFailure, match="ortuş"):
        ANKET_PKA(k, pd.Timestamp("2023-12-01"), TUF)


def test_bant_sabitleri_belgeli():
    assert ANKET_SERISI == "tufe_beklenti_pka"
    assert BANT_TABANI == 0.2


# --- Motor entegrasyonu: lag=0 → M anketi cutoff M+2'de kesitte yayında -------
# survey.py publication_lag_days=0 iddiası burada sabitlenir: lag sonradan
# değişirse gerçek koşumda anket_pka satırları sessizce NaN olur; bu testler
# o zaman KIRMIZI döner.


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    # tests/test_backtest.py:45-49 deseni — veri kökü tmp_path'e taşınır.
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


def _meta(name: str, lag: int) -> SeriesMeta:
    return SeriesMeta(
        name=name,
        source="test",
        url="https://example.org/test",
        frequency="aylık",
        units="yuzde",
        publication_lag_days=lag,
        license_note="lisans: test",
    )


def _serileri_kaydet():
    """Anket (lag=0) + hedef (lag=3) serilerini tmp depoya yazar.

    Anket değeri ay sırası + 1 (2023-01 → 1.0); hedef gerçekleri her ay
    ankete göre +0.5 sapmalı → tarihsel hataların %80 persentili 0.5.
    """
    anket = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", "2023-12-01", freq="MS"),
            "value": [float(i) + 1.0 for i in range(12)],
            "series_id": ANKET_SERISI,
        }
    )
    save_series(_meta(ANKET_SERISI, lag=0), anket)
    hedef = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", "2024-01-01", freq="MS"),
            "value": [float(i) + 1.5 for i in range(13)],
            "series_id": HEDEF,
        }
    )
    save_series(_meta(HEDEF, lag=3), hedef)


def test_lag0_anket_m_kesitte_yayinda(data_root):
    # cutoff = M sonu + CUTOFF_OFFSET_DAYS → M anket satırı kesitte.
    _serileri_kaydet()
    cutoff = pd.Timestamp("2023-06-30") + pd.Timedelta(days=CUTOFF_OFFSET_DAYS)
    kesit_anket = asof_monthly(ANKET_SERISI, cutoff)
    assert pd.Timestamp("2023-06-01") in kesit_anket.index
    assert kesit_anket.loc["2023-06-01", "value"] == pytest.approx(6.0)


def test_anket_pka_run_backtest_uzerinde_dolu_satir(data_root):
    # ANKET_PKA gerçek motorla koşar: lag=0 bozulursa tüm satırlar sessizce
    # NaN olurdu — bu test o regresyonu yakalar.
    _serileri_kaydet()
    sonuc = run_backtest(
        {MODEL_ADI: ANKET_PKA},
        HEDEF,
        pd.Timestamp("2023-02-01"),
        pd.Timestamp("2023-06-01"),
    )
    assert len(sonuc) == 5
    assert sonuc["point"].notna().all()
    for satir in sonuc.itertuples():
        beklenen = float(satir.target_month.month)  # anket değeri = ay sırası + 1
        assert satir.point == pytest.approx(beklenen), f"{satir.target_month:%Y-%m}"
        assert satir.lower == pytest.approx(beklenen - 0.5)
        assert satir.upper == pytest.approx(beklenen + 0.5)
        # actual = anket + 0.5, bant ±0.5 → tam üst sınırdan içerde (inclusive).
        assert bool(satir.hit80)
