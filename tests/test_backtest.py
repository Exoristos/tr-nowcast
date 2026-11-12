"""backtest (T12) birim testleri — tamamen offline; veri kökü tmp_path'e taşınır.

Review Focus kapsamı:
1. Gelecek sızıntısı: kesit cutoff'tan sonraki gerçek değerler değişince
   run_backtest çıktısı bit-bit aynı kalmalı.
2. Günlük seri kesme: yarım (tanımsız) ay ortalamaya girmez.
3. Yayın lag'i: lag=3 seride cutoff'ta M ayı yok, son ay M-1.
+ ModelFailure: NaN satır yazılır, motor devam eder.
"""

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
from trnowcast.store import SeriesMeta, save_series


def make_meta(**overrides) -> SeriesMeta:
    defaults = {
        "name": "test_serisi",
        "source": "test",
        "url": "https://example.org/veri.csv",
        "frequency": "aylık",
        "units": "yuzde",
        "publication_lag_days": 3,
        "license_note": "lisans: test",
    }
    defaults.update(overrides)
    return SeriesMeta(**defaults)


def make_df(dates, values, series_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "value": values, "series_id": series_id}
    )


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


@pytest.fixture
def aylik_seri(data_root):
    # Değerler ay sırasıyla artar: motor sızarsa tahmin gelecekteki değeri kullanır.
    save_series(
        make_meta(name="sahte_tufe"),
        make_df(
            ["2019-01-01", "2019-02-01", "2019-03-01", "2019-04-01", "2019-05-01", "2019-06-01"],
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "sahte_tufe",
        ),
    )


def son_deger_modeli(kesit, hedef_ay, target="sahte_tufe") -> ForecastPoint:
    """Sahte ModelFn: kesitteki hedef serinin son değerini döndürür (naive)."""
    df = kesit[target]
    son = float(df["value"].iloc[-1])
    return ForecastPoint(
        target_month=hedef_ay, point=son, lower=son - 0.5, upper=son + 0.5, model="kesit-sonu"
    )


# --- Review Focus 3: yayın lag'i tutarlılığı -------------------------------


def test_lag3_cutoffta_m_yok_m_eksi_bir_var(data_root, aylik_seri):
    # Hedef ay M=2019-03: kesit = M ay sonunun + CUTOFF_OFFSET_DAYS günü.
    cutoff = pd.Timestamp("2019-03-31") + pd.Timedelta(days=CUTOFF_OFFSET_DAYS)
    assert cutoff == pd.Timestamp("2019-04-02")
    kesit = asof_monthly("sahte_tufe", cutoff)
    # lag=3 → Mart (M) kesitte olamaz; son girilen ay Şubat (M-1).
    assert list(kesit.index) == [pd.Timestamp("2019-01-01"), pd.Timestamp("2019-02-01")]
    assert kesit.loc["2019-02-01", "value"] == pytest.approx(2.0)


# --- Review Focus 2: günlük seri kesme -------------------------------------


def test_gunluk_yarim_ay_kesite_girmez(data_root):
    ocak = pd.date_range("2019-01-01", "2019-01-31")
    mart = pd.date_range("2019-03-01", "2019-03-31")
    dates = list(ocak) + ["2019-02-01", "2019-02-15"] + list(mart)
    # Ocak tam: ort 15; Şubat yarım (1–15): satırı hiç yok; Mart tam: ort 35.
    values = [15.0] * len(ocak) + [5.0, 7.0] + [35.0] * len(mart)
    save_series(
        make_meta(
            name="sahte_gunluk", frequency="günlük", publication_lag_days=0
        ),
        make_df(dates, values, "sahte_gunluk"),
    )
    kesit = asof_monthly("sahte_gunluk", pd.Timestamp("2019-06-01"))
    assert list(kesit.index) == [pd.Timestamp("2019-01-01"), pd.Timestamp("2019-03-01")]
    assert kesit.loc["2019-01-01", "value"] == pytest.approx(15.0)
    assert kesit.loc["2019-03-01", "value"] == pytest.approx(35.0)


def test_gunluk_delikli_ay_kesite_girmez(data_root):
    # Ay ortası delikli ay (kaynak kesintisi): uçları dolu olsa da TANIMSIZ sayılır.
    ocak = pd.date_range("2019-01-01", "2019-01-31")
    mart = pd.date_range("2019-03-01", "2019-03-31")
    # Şubat: uçları dolu ama ortada 25 gün eksik.
    subat_delikli = ["2019-02-01", "2019-02-02", "2019-02-28"]
    dates = list(ocak) + subat_delikli + list(mart)
    values = [10.0] * len(ocak) + [1.0, 2.0, 3.0] + [30.0] * len(mart)
    save_series(
        make_meta(name="sahte_gunluk", frequency="günlük", publication_lag_days=0),
        make_df(dates, values, "sahte_gunluk"),
    )
    kesit = asof_monthly("sahte_gunluk", pd.Timestamp("2019-06-01"))
    assert list(kesit.index) == [pd.Timestamp("2019-01-01"), pd.Timestamp("2019-03-01")]
    assert kesit.loc["2019-01-01", "value"] == pytest.approx(10.0)
    assert kesit.loc["2019-03-01", "value"] == pytest.approx(30.0)


def test_model_kesitinde_yarim_ay_yok(data_root):
    # run_backtest'in modele verdiği sözlükte de yarım ay satırı olmamalı.
    dates = list(pd.date_range("2019-02-01", "2019-02-28")) + ["2019-03-01", "2019-03-10"]
    values = [1.0] * 28 + [3.0, 4.0]
    save_series(
        make_meta(name="sahte_gunluk", frequency="günlük", publication_lag_days=0),
        make_df(dates, values, "sahte_gunluk"),
    )
    yakalanan = {}

    def kayit_modeli(kesit, hedef_ay, target) -> ForecastPoint:
        yakalanan[hedef_ay] = kesit
        return ForecastPoint(hedef_ay, 0.0, -1.0, 1.0, "kayit")

    run_backtest(
        {"kayit": kayit_modeli},
        "sahte_gunluk",
        pd.Timestamp("2019-03-01"),
        pd.Timestamp("2019-03-01"),
    )
    kesit = yakalanan[pd.Timestamp("2019-03-01")]["sahte_gunluk"]
    assert list(kesit.index) == [pd.Timestamp("2019-02-01")]  # Şubat tam → kesitte
    # Mart yarım (10'unda bitiyor) → sözlükte satırı hiç yok.


# --- Review Focus 1: gelecek sızıntısı --------------------------------------


def test_gelecek_sizintisi_cikti_bit_bit_ayni(data_root, aylik_seri):
    sonuc1 = run_backtest(
        {"kesit-sonu": son_deger_modeli},
        "sahte_tufe",
        pd.Timestamp("2019-02-01"),
        pd.Timestamp("2019-04-01"),
    )
    # Sızıntısızlığın doğrudan kanıtı: kesitteki son değer bir önceki ayın değeri.
    for m in pd.period_range("2019-02", "2019-04", freq="M"):
        satir = sonuc1[sonuc1["target_month"] == m.start_time].iloc[0]
        assert satir["point"] == float(m.month - 1)

    # Kesit cutoff'larının hepsinden SONRA yayınlanan ayların değerlerini değiştir;
    # motor kesiti cutoff'ta kırdığı için çıktı bit-bit aynı kalmalı.
    save_series(
        make_meta(name="sahte_tufe"),
        make_df(["2019-05-01", "2019-06-01"], [999.0, -999.0], "sahte_tufe"),
    )
    sonuc2 = run_backtest(
        {"kesit-sonu": son_deger_modeli},
        "sahte_tufe",
        pd.Timestamp("2019-02-01"),
        pd.Timestamp("2019-04-01"),
    )
    pd.testing.assert_frame_equal(sonuc1, sonuc2, check_exact=True)


# --- ModelFailure -----------------------------------------------------------


def test_model_failure_nan_satir_ve_devam(data_root, aylik_seri):
    def coken_model(kesit, hedef_ay, target) -> ForecastPoint:
        if hedef_ay == pd.Timestamp("2019-03-01"):
            raise ModelFailure("yakınsama yok")
        return son_deger_modeli(kesit, hedef_ay)

    sonuc = run_backtest(
        {"kesit-sonu": coken_model},
        "sahte_tufe",
        pd.Timestamp("2019-02-01"),
        pd.Timestamp("2019-04-01"),
    )
    # Motor çöken ayı atlamadı: 3 ayın üçü de satır.
    assert len(sonuc) == 3
    coken = sonuc[sonuc["target_month"] == pd.Timestamp("2019-03-01")].iloc[0]
    assert pd.isna(coken["point"])
    assert pd.isna(coken["abs_error"])
    assert pd.isna(coken["hit80"])
    # Devam etti: sonraki ay dolu satır (point=3, actual=4, hata=1).
    saglam = sonuc[sonuc["target_month"] == pd.Timestamp("2019-04-01")].iloc[0]
    assert saglam["point"] == pytest.approx(3.0)
    assert saglam["actual"] == pytest.approx(4.0)
    assert saglam["abs_error"] == pytest.approx(1.0)


# --- Çıktı şeması -----------------------------------------------------------


def test_cikti_semasi_ve_satir_sirasi(data_root, aylik_seri):
    def genis_model(kesit, hedef_ay, target) -> ForecastPoint:
        son = float(kesit[target]["value"].iloc[-1])
        return ForecastPoint(hedef_ay, son, son - 5.0, son + 5.0, "genis")

    sonuc = run_backtest(
        {"a": son_deger_modeli, "b": genis_model},
        "sahte_tufe",
        pd.Timestamp("2019-02-01"),
        pd.Timestamp("2019-03-01"),
    )
    assert list(sonuc.columns) == [
        "model",
        "target_month",
        "point",
        "lower",
        "upper",
        "actual",
        "abs_error",
        "hit80",
    ]
    # Satır sırası: model → (her model bloğu içinde) tarih artan.
    assert list(sonuc["model"]) == ["a", "a", "b", "b"]
    for model_adi in ("a", "b"):
        tarihler = list(sonuc.loc[sonuc["model"] == model_adi, "target_month"])
        assert tarihler == sorted(tarihler)

    a_mart = sonuc[(sonuc["model"] == "a") & (sonuc["target_month"] == pd.Timestamp("2019-03-01"))].iloc[0]
    # Dar bant (±0.5) şoku yakalayamıyor: point=2, actual=3 → hit80 False.
    assert not a_mart["hit80"]
    b_mart = sonuc[(sonuc["model"] == "b") & (sonuc["target_month"] == pd.Timestamp("2019-03-01"))].iloc[0]
    # Genis bant (±5): actual bandın içinde → hit80 True.
    assert b_mart["hit80"]
