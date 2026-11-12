"""FAO çekici birim testleri — tamamen offline (tests/fixtures/fao_fpis.csv)."""

from pathlib import Path

import pandas as pd
import pytest

import trnowcast.sources
from trnowcast.sources import SourceError, fao


def test_fao_paylasilan_source_error_kullaniyor() -> None:
    # T7 CLI `trnowcast.sources.SourceError` üzerinden yakalar; FAO kendi
    # sınıfını tanımlarsa o except FAO hatalarını kaçırmış olurdu (denetçi T4).
    assert fao.SourceError is trnowcast.sources.SourceError

FIXTURE = Path(__file__).parent / "fixtures" / "fao_fpis.csv"


def _fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_fixture_schema() -> None:
    df = fao.parse_fpis(_fixture_text())
    assert list(df.columns) == ["date", "value", "series_id"]
    # pandas 3'te to_datetime datetime64[us] verir; sözleşme datetime64 ailesidir
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["value"])
    assert (df["series_id"] == fao.SERIES_NAME).all()
    assert df["date"].is_monotonic_increasing


def test_parse_fixture_values() -> None:
    df = fao.parse_fpis(_fixture_text())
    # 12 (1990) + 6 (2026) veri satırı; başlık ve boş ayraç satırları karışmamalı
    assert len(df) == 18
    first = df.iloc[0]
    assert first["date"] == pd.Timestamp("1990-01-01")  # ay başı normalizasyonu
    assert first["value"] == pytest.approx(64.4)
    last = df.iloc[-1]
    assert last["date"] == pd.Timestamp("2026-09-01")
    assert last["value"] == pytest.approx(136.0)


def test_parse_skips_empty_value_row() -> None:
    text = (
        "FAO Food Price Index,\n"
        "2014-2016=100,\n"
        "Date,Food Price Index,Meat\n"
        "\n"
        "2026-01,120.0,100.0\n"
        "2026-02,,99.0\n"
        "2026-03,121.5,101.0"
    )
    df = fao.parse_fpis(text)
    assert list(df["date"]) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01")]
    assert list(df["value"]) == [120.0, 121.5]


def test_parse_unknown_schema_raises() -> None:
    with pytest.raises(SourceError, match="Date"):
        fao.parse_fpis("bu bir csv degil\nikinci satir\n")
    with pytest.raises(SourceError):
        fao.parse_fpis("")


def test_parse_missing_total_column_raises() -> None:
    text = "Date,Et,Sut\n1990-01,64.4,53.5\n"
    with pytest.raises(SourceError, match="Food Price Index"):
        fao.parse_fpis(text)


def test_parse_malformed_date_raises() -> None:
    text = "Date,Food Price Index\n1990-01,64.4\n01/1990,66.0\n"
    with pytest.raises(SourceError, match="tarih"):
        fao.parse_fpis(text)


def test_parse_non_numeric_value_raises() -> None:
    text = "Date,Food Price Index\n1990-01,abc\n"
    with pytest.raises(SourceError, match="abc"):
        fao.parse_fpis(text)


def test_meta_registry_bilgileri() -> None:
    meta = fao.META
    assert meta.name == fao.SERIES_NAME == "fao_gida_endeks"
    assert meta.frequency == "aylık"
    assert meta.publication_lag_days == 30  # plan T4: ≈30
    assert meta.units == "2014-2016=100"  # dosyanın kendi taban satırından
    assert meta.source == "FAO"
    assert meta.url == fao.DATA_URL
    assert meta.url.startswith("https://www.fao.org/")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://fao.org/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://10.0.0.7/x",
        "https://192.168.1.10/x",
        "https://169.254.169.254/latest",
        "https://[::1]/x",
        "https://[fc00::1]/x",
    ],
)
def test_validate_url_rejects(url: str) -> None:
    with pytest.raises(SourceError):
        fao._validate_url(url)


def test_validate_url_accepts_data_url() -> None:
    fao._validate_url(fao.DATA_URL)  # hata fırlatmamalı


def test_fetch_fixture_ile(monkeypatch: pytest.MonkeyPatch) -> None:
    class SahteYanit:
        content = _fixture_text().encode("utf-8")

        def raise_for_status(self) -> None:
            return None

    def sahte_get(url: str, timeout: float, **kwargs: object) -> SahteYanit:
        assert url == fao.DATA_URL
        return SahteYanit()

    monkeypatch.setattr(fao.requests, "get", sahte_get)
    df = fao.fetch()
    assert len(df) == 18
    assert df["date"].iloc[-1] == pd.Timestamp("2026-09-01")


def test_fetch_all_depoya_yazar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-08-01")],
            "value": [134.0],
            "series_id": [fao.SERIES_NAME],
        }
    )
    hedef = tmp_path / "fao.parquet"
    kayit: dict[str, object] = {}

    def sahte_save(meta: object, frame: pd.DataFrame) -> Path:
        kayit["meta"], kayit["df"] = meta, frame
        return hedef

    monkeypatch.setattr(fao, "fetch", lambda: df)
    monkeypatch.setattr(fao, "save_series", sahte_save)
    assert fao.fetch_all() == [hedef]
    assert kayit["meta"] is fao.META
    pd.testing.assert_frame_equal(kayit["df"], df)


@pytest.mark.live
def test_fetch_live() -> None:
    df = fao.fetch()
    assert not df.empty
    assert df["date"].iloc[-1] > pd.Timestamp("2024-01-01")
