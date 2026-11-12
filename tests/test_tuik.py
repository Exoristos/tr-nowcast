"""TÜİK çekici birim testleri: ağ güvenliği, kaynak önceliği, T2 sözleşmesi.

Tamamen offline: ağ sınırı (_cek / requests.get) ve yazım sınırı (save_series)
monkeypatch edilir; gerçek SeriesMeta sözleşmesi korunur. Canlı çağrı yalnızca
`live` işaretli testtedir (varsayılan koşuda hariç).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from trnowcast import store
from trnowcast.sources import SourceError, tuik
from trnowcast.store import SeriesMeta

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _json_oku(dosya: str) -> dict:
    return json.loads((FIXTURE_DIR / dosya).read_text(encoding="utf-8"))


def _xlsx_oku(dosya: str) -> bytes:
    return (FIXTURE_DIR / dosya).read_bytes()


def test_series_sozlugu_planla_ayni():
    assert tuik.SERIES == {
        "turkiye_tufe_aylik_yuzde_tuik": "aylik_yuzde",
        "turkiye_tufe_endeks_tuik": "endeks",
    }


def test_sourceerror_401_bearer_token_mesaji(monkeypatch):
    class SahteYanit:
        status_code = 401
        text = "unauthorized"

    monkeypatch.setattr(tuik.requests, "get", lambda *a, **k: SahteYanit())
    with pytest.raises(SourceError, match="Bearer token"):
        tuik._cek()


def test_sourceerror_403_ayni_mesaji(monkeypatch):
    class SahteYanit:
        status_code = 403
        text = "forbidden"

    monkeypatch.setattr(tuik.requests, "get", lambda *a, **k: SahteYanit())
    with pytest.raises(SourceError, match="Bearer token"):
        tuik._cek()


def test_sourceerror_ag_hatasi(monkeypatch):
    def _kop(*a, **k):
        raise tuik.requests.ConnectionError("bağlantı sıfırlandı")

    monkeypatch.setattr(tuik.requests, "get", _kop)
    with pytest.raises(SourceError):
        tuik._cek()


def test_url_guvenlik_denetimi():
    tuik._validate_url(tuik.SDMX_URL)  # gerçek adres kabul edilir
    for engelli in (
        "http://localhost/rest/data",
        "https://127.0.0.1/rest/data",
        "https://10.0.0.5/rest/data",
        "https://192.168.1.1/rest/data",
        "ftp://nsiws.tuik.gov.tr/rest/data",
        "https://nsiws.ornek-uyduruk.com/rest/data",
    ):
        with pytest.raises(SourceError):
            tuik._validate_url(engelli)


def test_fetch_oncelikle_manuel_dosya(tmp_path, monkeypatch):
    """data/raw/tuik_tufe.xlsx varsa fetch ağa çıkmaz; registry url 'manuel' notu taşır."""
    ham = tmp_path / "raw"
    ham.mkdir()
    (ham / "tuik_tufe.xlsx").write_bytes(_xlsx_oku("tuik_tufe.xlsx"))
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path)

    def _aga_cikma(*a, **k):
        raise AssertionError("manuel dosya varken ağa çıkılmamalı")

    monkeypatch.setattr(tuik.requests, "get", _aga_cikma)

    df = tuik.fetch()

    assert set(df["series_id"]) == {"endeks", "aylik_yuzde"}
    assert len(df) == 12

    kayitlar = []
    monkeypatch.setattr(tuik, "save_series", lambda meta, d: kayitlar.append((meta, d)))
    tuik.fetch_all()
    assert len(kayitlar) == 2
    for meta, _ in kayitlar:
        assert meta.url == "manuel: tuik_tufe.xlsx (doğrulanmamış kaynak)"


def test_fetch_all_sdmx_meta_sozlesmesi(tmp_path, monkeypatch):
    """fetch_all gerçek SeriesMeta sözleşmesiyle depoya yazar (ağ sınırı sahtelenir).

    DATA_ROOT tmp_path'e yönlendirilir: test, kullanıcının data/raw/tuik_tufe.xlsx
    dosyasının varlığına (manuel yol önceliğine) bağlı olmamalı (denetçi bulgusu 3).
    """
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(tuik, "_cek", lambda: _json_oku("tuik_tufe_sdmx.json"))

    kayitlar = []

    def _sahte_save_series(meta, df):
        kayitlar.append((meta, df))
        return Path("data/processed") / f"{meta.name}.parquet"

    monkeypatch.setattr(tuik, "save_series", _sahte_save_series)

    yollar = tuik.fetch_all()

    assert yollar == [
        Path("data/processed/turkiye_tufe_aylik_yuzde_tuik.parquet"),
        Path("data/processed/turkiye_tufe_endeks_tuik.parquet"),
    ]
    assert len(kayitlar) == 2
    isimler = {meta.name: meta for meta, _ in kayitlar}
    # yedek boru ayrı adlara yazar (denetçi bulgusu 3): registry kaynak izi karışmasın
    assert set(isimler) == {"turkiye_tufe_aylik_yuzde_tuik", "turkiye_tufe_endeks_tuik"}
    for meta, df in kayitlar:
        assert isinstance(meta, SeriesMeta)  # gerçek T2 sözleşmesi
        assert meta.source == "TÜİK"
        assert meta.url == tuik.SDMX_URL
        assert meta.frequency == "aylık"
        assert meta.publication_lag_days == 3  # plan T5 step 3
        assert isinstance(df, pd.DataFrame) and len(df) > 0


@pytest.mark.live
def test_live_tuik_fetch():
    """Canlı doğrulama: manuel dosya veya SDMX'ten veri gelir; ikisi de yoksa skip."""
    try:
        df = tuik.fetch()
    except SourceError as hata:
        pytest.skip(f"canlı TÜİK kaynağı yok: {hata}")
    assert not df.empty
    assert set(df["series_id"]) <= {"endeks", "aylik_yuzde"}
    assert df["date"].max() > pd.Timestamp("2020-01-01")
