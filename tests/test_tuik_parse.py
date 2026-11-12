"""TÜİK JSONstat (SDMX) ayrıştırıcı birim testleri — tamamen offline.

Fixture "değerler sentetik, yalnız biçim kanıtı" ilkesiyle kuruludur:
tuik_tufe_sdmx.json TÜİK SDMX JSONstat 2.0 şemasını temsil eder; gerçek
TÜİK verisi değildir. TR-yerel xlsx ayrıştırıcı testleri test_tuik_tablo.py'de.
"""

import itertools
import json
from pathlib import Path

import pandas as pd
import pytest

from trnowcast.sources import SourceError, tuik

FIXTURE_DIR = Path(__file__).parent / "fixtures"

ENDEKS_FIXTURE = [98.1, 99.24, 100.9, 101.02, 102.55, 103.77]
AYLIK_FIXTURE = [1.15, 1.16, 1.67, 0.12, 1.51, 1.19]


def _json_oku(dosya: str) -> dict:
    return json.loads((FIXTURE_DIR / dosya).read_text(encoding="utf-8"))


def _seri(df: pd.DataFrame, kod: str) -> pd.DataFrame:
    return df[df["series_id"] == kod].sort_values("date")


def test_jsonstat_fixture_iki_seri_semasi():
    df = tuik.parse_jsonstat(_json_oku("tuik_tufe_sdmx.json"))

    assert list(df.columns) == ["date", "value", "series_id"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["value"])
    # kaynağın ölçü kimlikleri (fetch_all meta.name'e çevirir)
    assert set(df["series_id"]) == {"endeks", "aylik_yuzde"}
    assert len(df) == 12
    assert (df["date"].dt.day == 1).all()
    for seri in ("endeks", "aylik_yuzde"):
        assert _seri(df, seri)["date"].is_monotonic_increasing

    endeks = _seri(df, "endeks")
    assert endeks["value"].tolist() == ENDEKS_FIXTURE
    assert endeks["date"].iloc[0] == pd.Timestamp("2025-01-01")
    assert _seri(df, "aylik_yuzde")["value"].tolist() == AYLIK_FIXTURE


def test_jsonstat_deger_null_atlanir():
    payload = _json_oku("tuik_tufe_sdmx.json")
    payload["value"] = [98.1, None, 100.9, None, 102.55, 103.77] + AYLIK_FIXTURE

    df = tuik.parse_jsonstat(payload)

    endeks = _seri(df, "endeks")
    assert endeks["value"].tolist() == [98.1, 100.9, 102.55, 103.77]
    assert endeks["date"].tolist() == [
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-03-01"),
        pd.Timestamp("2025-05-01"),
        pd.Timestamp("2025-06-01"),
    ]


def test_jsonstat_aylik_yoksa_endeksten_turetilir():
    # TÜİK yanıtı aylık % ölçüsünü içermezse plan T5 uyarınca endeksten türetilir
    payload = _json_oku("tuik_tufe_sdmx.json")
    payload["size"] = [1, 1, 1, 6]
    payload["value"] = ENDEKS_FIXTURE
    kategori = payload["dimension"]["DEGISIM"]["category"]
    kategori["index"] = {"IDX": 0}
    kategori["label"] = {"IDX": "Genel endeks (2025=100)"}

    df = tuik.parse_jsonstat(payload)

    assert set(df["series_id"]) == {"endeks", "aylik_yuzde"}
    beklenen = [(b / a - 1) * 100 for a, b in itertools.pairwise(ENDEKS_FIXTURE)]
    aylik = _seri(df, "aylik_yuzde")
    assert len(aylik) == 5  # ilk ay için önceki ay yok: türetme o ayı üretmez
    for got, want in zip(aylik["value"], beklenen):
        assert got == pytest.approx(want, rel=1e-9)
    assert _seri(df, "endeks")["value"].tolist() == ENDEKS_FIXTURE


def test_jsonstat_aylik_bos_ay_endeksten_tamamlanir():
    # aylık ölçünün en güncel ayı null ise o ay sessizce düşmemeli; endeksten
    # türetilerek tamamlanmalı (denetçi bulgusu 4)
    payload = _json_oku("tuik_tufe_sdmx.json")
    payload["value"] = ENDEKS_FIXTURE + [1.15, 1.16, 1.67, 0.12, 1.51, None]

    df = tuik.parse_jsonstat(payload)

    aylik = _seri(df, "aylik_yuzde")
    assert len(aylik) == 6
    assert aylik["value"].tolist()[:5] == [1.15, 1.16, 1.67, 0.12, 1.51]
    assert aylik["value"].iloc[-1] == pytest.approx((103.77 / 102.55 - 1) * 100, rel=1e-9)


def test_jsonstat_12_aylik_ortalama_olcu_karismaz():
    # gerçek TÜİK ölçü kümesinde 'Yıllık değişim' ve '12 aylık ortalama değişim'
    # de vardır; 'aylık değişim' seçimi onları yakalamamalı (denetçi bulgusu 1)
    payload = _json_oku("tuik_tufe_sdmx.json")
    kat = payload["dimension"]["DEGISIM"]["category"]
    kat["index"] = {"IDX": 0, "AYLIK": 1, "YILLIK": 2, "ORT12": 3}
    kat["label"] = {
        "IDX": "Genel endeks (2025=100)",
        "AYLIK": "Aylık değişim (%)",
        "YILLIK": "Yıllık değişim (%)",
        "ORT12": "12 aylık ortalama değişim (%)",
    }
    payload["size"] = [1, 1, 4, 6]
    payload["value"] = ENDEKS_FIXTURE + AYLIK_FIXTURE + [5.0] * 6 + [9.0] * 6

    df = tuik.parse_jsonstat(payload)

    assert _seri(df, "aylik_yuzde")["value"].tolist() == AYLIK_FIXTURE
    assert _seri(df, "endeks")["value"].tolist() == ENDEKS_FIXTURE


def test_jsonstat_siklik_etiketi_olcu_sanilmaz():
    # FREQ'in 'Aylık'/'Üç Aylık' etiketleri ölçü boyutu sanılmamalı: koruma
    # olmasaydı FREQ (id sırasında ilk) ölçü boyutu seçilir, endeks etiketi
    # bulunamayacağı için bu GEÇERLİ dataset SourceError'a düşerdi
    payload = _json_oku("tuik_tufe_sdmx.json")
    payload["id"] = ["FREQ", "DEGISIM", "time"]
    payload["size"] = [2, 2, 6]
    freq_kat = payload["dimension"]["FREQ"]["category"]
    freq_kat["index"] = {"M": 0, "Q": 1}
    freq_kat["label"] = {"M": "Aylık", "Q": "Üç Aylık"}
    del payload["dimension"]["REF_AREA"]
    payload["value"] = ENDEKS_FIXTURE + AYLIK_FIXTURE + [None] * 12  # FREQ=Q boş

    df = tuik.parse_jsonstat(payload)

    assert set(df["series_id"]) == {"endeks", "aylik_yuzde"}
    assert len(df) == 12
    assert _seri(df, "endeks")["value"].tolist() == ENDEKS_FIXTURE


def test_jsonstat_beklenmedik_sema_value_anahtari_yok():
    payload = _json_oku("tuik_tufe_sdmx.json")
    del payload["value"]
    with pytest.raises(SourceError):
        tuik.parse_jsonstat(payload)


def test_jsonstat_beklenmedik_sema_zaman_boyutu_yok():
    payload = _json_oku("tuik_tufe_sdmx.json")
    del payload["dimension"]["time"]
    payload["id"] = ["FREQ", "REF_AREA", "DEGISIM"]
    payload["size"] = [1, 1, 2]
    with pytest.raises(SourceError):
        tuik.parse_jsonstat(payload)


def test_jsonstat_beklenmedik_sema_olcu_boyutu_yok():
    # ölçü etiketleri endeks/aylık-değişim taşımıyorsa şema tanınmaz
    payload = _json_oku("tuik_tufe_sdmx.json")
    payload["dimension"]["DEGISIM"]["category"]["label"] = {
        "IDX": "Kod A",
        "AYLIK": "Kod B",
    }
    with pytest.raises(SourceError):
        tuik.parse_jsonstat(payload)


def test_jsonstat_endeks_olcusu_hic_yoksa_hata():
    # yalnız aylık ölçü gelirse endeks serisi üretilemez: sessiz eksik dönüş yok
    payload = _json_oku("tuik_tufe_sdmx.json")
    payload["size"] = [1, 1, 1, 6]
    payload["value"] = AYLIK_FIXTURE
    kategori = payload["dimension"]["DEGISIM"]["category"]
    kategori["index"] = {"AYLIK": 0}
    kategori["label"] = {"AYLIK": "Aylık değişim (%)"}
    with pytest.raises(SourceError):
        tuik.parse_jsonstat(payload)
