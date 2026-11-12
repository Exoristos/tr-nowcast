"""FRED çekici birim testleri — tamamen offline (fixtures + inline CSV örnekleri).

Ağ çağrısı yalnızca `live` işaretli testte yapılır; varsayılan koşuda hariçtir.
"""

from pathlib import Path

import pandas as pd
import pytest

from trnowcast.sources import SourceError, fred
from trnowcast.store import SeriesMeta

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _oku(dosya: str) -> str:
    return (FIXTURE_DIR / dosya).read_text(encoding="utf-8")


def test_series_sozlugu_planla_ayni():
    assert fred.SERIES == {
        "turkiye_tufe_endeks_fred": "TURCPIALLMINMEI",
        "brent_gunluk": "DCOILBRENTEU",
    }


def test_tufe_fixture_long_format_semasi():
    df = fred.parse_csv(_oku("fred_turcpiallminmei.csv"), "TURCPIALLMINMEI")

    assert list(df.columns) == ["date", "value", "series_id"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["value"])
    assert (df["series_id"] == "TURCPIALLMINMEI").all()
    assert df["date"].is_monotonic_increasing
    assert df["value"].notna().all()

    # aylık seri ay-başı tarihlerde gelir
    assert len(df) == 52
    assert (df["date"].dt.day == 1).all()
    assert df["date"].iloc[0] == pd.Timestamp("2021-01-01")
    assert df["date"].iloc[-1] == pd.Timestamp("2025-04-01")
    assert df["value"].iloc[-1] == pytest.approx(1167.845, abs=1e-6)


def test_brent_fixture_gunluk_tarih_korunur():
    df = fred.parse_csv(_oku("fred_dcoilbrente.csv"), "DCOILBRENTEU")

    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["value"])
    assert (df["series_id"] == "DCOILBRENTEU").all()
    assert df["date"].is_monotonic_increasing

    # fixture'daki 120 satırdan ikisi (ABD tatilleri) eksik değerli: düşürülmüş olmalı
    assert len(df) == 118
    dusenler = df["date"].isin([pd.Timestamp("2026-05-25"), pd.Timestamp("2026-08-31")])
    assert not dusenler.any()

    # gün hassasiyeti korunmalı (ay-başına yuvarlanmamalı)
    assert (df["date"].dt.day != 1).any()
    assert df["date"].iloc[-1] == pd.Timestamp("2026-11-03")


def test_nokta_degerleri_nan_olarak_dusurulur():
    # FRED bazı dosyalarda eksik değeri "." ile işaretler (canlı brent dosyası boş alan verir)
    metin = "observation_date,ORNEK\n2024-01-01,10.5\n2024-02-01,.\n2024-03-01,12.0\n"
    df = fred.parse_csv(metin, "ORNEK")

    assert len(df) == 2
    assert df["date"].tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01")]
    assert df["value"].tolist() == [10.5, 12.0]


def test_sourceerror_bos_govde():
    with pytest.raises(SourceError):
        fred.parse_csv("", "ORNEK")


def test_sourceerror_basliksiz_html_govde():
    # FRED bir sorun durumunda CSV yerine HTML hata sayfası döndürebilir
    with pytest.raises(SourceError):
        fred.parse_csv("<html><body>Hata olustu, tekrar deneyin</body></html>", "ORNEK")


def test_sourceerror_tanimdis_baslik():
    with pytest.raises(SourceError):
        fred.parse_csv("sürüm,sayı\n1,2\n", "ORNEK")


def test_sourceerror_tarih_ayristirilamaz():
    metin = "observation_date,ORNEK\nbu-tarih-degil,1.5\n"
    with pytest.raises(SourceError):
        fred.parse_csv(metin, "ORNEK")


def test_sourceerror_sayi_ayristirilamaz():
    metin = "observation_date,ORNEK\n2024-01-01,onbes\n"
    with pytest.raises(SourceError):
        fred.parse_csv(metin, "ORNEK")


def test_sourceerror_tumu_eksik_degerli_yanit():
    # Kullanılabilir hiç gözlem yoksa sessiz boş çerçeve değil SourceError:
    # aksi halde fetch_all boş parquet yazıp registry'yi "güncel" sanıp tazeler.
    metin = "observation_date,ORNEK\n2024-01-01,.\n2024-02-01,\n"
    with pytest.raises(SourceError):
        fred.parse_csv(metin, "ORNEK")


def test_sourceerror_gecersiz_seri_kodu_url_ye_girmez():
    with pytest.raises(SourceError):
        fred._seri_url("ornek/../sneak")


def test_fetch_all_meta_ile_depoya_yazar(monkeypatch):
    """fetch_all gerçek SeriesMeta sözleşmesiyle (T2) depoya yazmalıdır.

    Yalnız ağ sınırı (fetch_series) ve yazım sınırı (save_series) sahtelenir;
    SeriesMeta kurulumu gerçek sınıfla yapılır — alan adı/frekans sözleşmesi
    değişirse bu test kırılır.
    """
    tufe = fred.parse_csv(_oku("fred_turcpiallminmei.csv"), "TURCPIALLMINMEI")
    brent = fred.parse_csv(_oku("fred_dcoilbrente.csv"), "DCOILBRENTEU")
    monkeypatch.setattr(
        fred, "fetch_series", lambda sid: tufe if sid == "TURCPIALLMINMEI" else brent
    )

    kayitlar = []

    def _sahte_save_series(meta, df):
        kayitlar.append((meta, df))
        return Path("data/processed") / f"{meta.name}.parquet"

    monkeypatch.setattr(fred, "save_series", _sahte_save_series)

    yollar = fred.fetch_all()

    assert yollar == [
        Path("data/processed/turkiye_tufe_endeks_fred.parquet"),
        Path("data/processed/brent_gunluk.parquet"),
    ]
    assert len(kayitlar) == 2

    meta_tufe, df_tufe = kayitlar[0]
    assert isinstance(meta_tufe, SeriesMeta)  # gerçek T2 sözleşmesi, sahte değil
    assert meta_tufe.name == "turkiye_tufe_endeks_fred"
    assert meta_tufe.source == "FRED"
    assert meta_tufe.url == "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TURCPIALLMINMEI"
    assert meta_tufe.frequency == "aylık"
    assert meta_tufe.publication_lag_days == 45
    assert (df_tufe["series_id"] == "TURCPIALLMINMEI").all()

    meta_brent, df_brent = kayitlar[1]
    assert meta_brent.name == "brent_gunluk"
    assert meta_brent.source == "FRED"
    assert meta_brent.url == "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
    assert meta_brent.frequency == "günlük"
    assert meta_brent.publication_lag_days == 2
    assert (df_brent["series_id"] == "DCOILBRENTEU").all()


@pytest.mark.live
def test_live_tufe_son_satir_2020_den_yeni():
    df = fred.fetch_series("TURCPIALLMINMEI")
    assert df["date"].max() > pd.Timestamp("2020-01-01")
