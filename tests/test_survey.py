"""TCMB beklenti anketi (T6) birim testleri — tamamen offline (fixtures)."""

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from trnowcast import store
from trnowcast.sources import evds, survey

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _oku(dosya: str) -> dict:
    return json.loads((FIXTURE_DIR / dosya).read_text(encoding="utf-8"))


def test_anket_seri_adi_ve_kodu_kilitli():
    # T10: değer PKA "uygun ortalama"dır, medyan değil → ad dürüst (pka), kod .U
    assert survey.SERIES_NAME == "tufe_beklenti_pka"
    # 2026-11-06 canlı teyit: .M (medyan) ve .U (uygun ortalama) kanalları farklı
    # değerler döndürür (Ekim: .M=2.20, .U=2.11); .U, TCMB PKA Ekim 2026 raporunun
    # "uygun ortalama" değeriyle birebir uyuşur — boru .U kanalını çeker
    assert survey.EVDS_CODE == "TP.BEK.S01.A.U"


def test_anket_fixture_aybasi_tarihler():
    # EVDS 3 aylık serilerde Tarih "YYYY-M" ve değerler nokta ondalıklı gelir
    # (2026-11-05 canlı); TR virgül desteği parser'da korunur (test_evds.py kapsar).
    # fixture: gerçek canlı kesit (2026-6..2026-10, TP.BEK.S01.A.U)
    df = evds.parse_json(_oku("evds_survey.json"), survey.EVDS_CODE)

    assert len(df) == 5
    assert (df["date"].dt.day == 1).all()
    assert df["date"].iloc[0] == pd.Timestamp("2026-06-01")
    assert df["value"].iloc[0] == pytest.approx(1.36)
    assert df["value"].iloc[-1] == pytest.approx(2.11)


def test_anket_fetch_aybasi_ve_seri_adi(monkeypatch):
    yakalanan: dict = {}

    def _sahte_get(self, series, start, end):
        yakalanan["series"] = series
        yakalanan["start"] = start
        return evds.parse_json(_oku("evds_survey.json"), series)

    monkeypatch.setattr(evds.EvdsClient, "get", _sahte_get)
    df = survey.fetch("test-anahtar")

    assert yakalanan["series"] == survey.EVDS_CODE
    assert yakalanan["start"] == survey.FETCH_START
    assert list(df.columns) == ["date", "value", "series_id"]
    assert (df["series_id"] == "tufe_beklenti_pka").all()
    # aylık seri ortak şemaya göre ay-başına normalize edilir
    assert (df["date"].dt.day == 1).all()
    assert len(df) == 5


def test_anket_fetch_anahtarsiz_evdskeymissing():
    with pytest.raises(evds.EvdsKeyMissing):
        survey.fetch(None)


def test_anket_fetch_all_gercek_store_ile(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(
        evds.EvdsClient,
        "get",
        lambda self, s, a, b: evds.parse_json(_oku("evds_survey.json"), s),
    )
    yollar = survey.fetch_all("test-anahtar")

    assert yollar == [tmp_path / "data" / "processed" / "tufe_beklenti_pka.parquet"]
    girdi = store.registry()["tufe_beklenti_pka"]
    assert girdi["frequency"] == "aylık"
    assert girdi["publication_lag_days"] == 0
    assert "uygun ortalama" in girdi["license_note"]  # istatistik türü registry'de açık
    assert "series=TP.BEK.S01.A.U" in girdi["url"]
    kayitli = store.load_series("tufe_beklenti_pka")
    assert (kayitli["series_id"] == "tufe_beklenti_pka").all()
    assert (kayitli["date"].dt.day == 1).all()


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("EVDS_API_KEY"), reason="EVDS_API_KEY yok")
def test_live_anket():
    df = survey.fetch(os.environ["EVDS_API_KEY"])
    assert df["value"].between(-5.0, 30.0).all()
    assert df["date"].max() > pd.Timestamp("2025-01-01")
