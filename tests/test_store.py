"""store (T2) birim testleri — tamamen offline; veri kökü tmp_path'e taşınır."""

from datetime import datetime

import pandas as pd
import pytest

from trnowcast import store
from trnowcast.store import SeriesMeta, load_series, registry, save_series


def make_meta(**overrides) -> SeriesMeta:
    defaults = {
        "name": "test_serisi",
        "source": "test",
        "url": "https://example.org/veri.csv",
        "frequency": "aylık",
        "units": "endeks",
        "publication_lag_days": 30,
        "license_note": "lisans: test",
    }
    defaults.update(overrides)
    return SeriesMeta(**defaults)


def make_df(dates, values, series_id="test_serisi") -> pd.DataFrame:
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "value": values, "series_id": series_id}
    )


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


def test_registry_bos_kenar_uygulamasi(data_root):
    assert registry() == {}


def test_save_parquet_ve_registry_yazar(data_root):
    meta = make_meta()
    path = save_series(meta, make_df(["2024-01-01", "2024-02-01"], [10.0, 11.0]))

    assert path == data_root / "processed" / "test_serisi.parquet"
    assert path.exists()
    reg = registry()
    assert set(reg) == {"test_serisi"}
    entry = reg["test_serisi"]
    # Dürüstlük sözleşmesi md.2: kaynak, URL, frekans, yayın gecikmesi kayıtlı.
    assert entry["url"] == "https://example.org/veri.csv"
    assert entry["source"] == "test"
    assert entry["frequency"] == "aylık"
    assert entry["units"] == "endeks"
    assert entry["publication_lag_days"] == 30
    assert entry["license_note"] == "lisans: test"
    assert entry["nan_threshold"] == 0.05
    datetime.fromisoformat(entry["last_fetched"])


def test_warn_range_registry_girdisine_yazilir(data_root):
    # denetçi bulgusu: değer aralığı eşiği quality'de değil meta'da yaşar;
    # registry girdisinde görünüp oradan okunabilir olmalı.
    save_series(make_meta(warn_range=(-2.0, 20.0)), make_df(["2024-01-01"], [10.0]))
    assert list(registry()["test_serisi"]["warn_range"]) == [-2.0, 20.0]


def test_warn_range_tanimli_degilse_none_yazilir(data_root):
    save_series(make_meta(), make_df(["2024-01-01"], [10.0]))
    assert registry()["test_serisi"]["warn_range"] is None


def test_warn_range_gecersiz_sekil_yapida_reddedilir(data_root):
    with pytest.raises(ValueError):
        make_meta(warn_range=(20.0, -2.0))  # alt > üst
    with pytest.raises(ValueError):
        make_meta(warn_range=(1.0,))  # tek öğe


def test_iki_kayit_duplicate_uretmez(data_root):
    meta = make_meta()
    df = make_df(["2024-01-01", "2024-02-01"], [10.0, 11.0])
    save_series(meta, df)
    save_series(meta, df)

    df_out = load_series("test_serisi")
    assert len(df_out) == 2
    assert df_out["date"].is_unique


def test_upsert_birlestirir_ve_son_deger_kalir(data_root):
    # İlk çekim: Ocak ve Şubat. İkinci çekim: Şubat revize + Mart yeni.
    save_series(make_meta(), make_df(["2024-01-01", "2024-02-01"], [1.0, 2.0]))
    save_series(make_meta(), make_df(["2024-02-01", "2024-03-01"], [2.5, 3.0]))

    df_out = load_series("test_serisi")
    assert list(df_out["date"]) == [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-02-01"),
        pd.Timestamp("2024-03-01"),
    ]
    assert list(df_out["value"]) == [1.0, 2.5, 3.0]


def test_giristeki_ayni_tarihli_satirlarda_son_deger_kalir(data_root):
    # Sırasız ve aynı tarihte iki satır: son satır kazanır, sonuç artan dizilir.
    save_series(
        make_meta(),
        make_df(["2024-02-01", "2024-01-01", "2024-02-01"], [2.0, 1.0, 9.0]),
    )

    df_out = load_series("test_serisi")
    assert list(df_out["date"]) == [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-02-01"),
    ]
    assert list(df_out["value"]) == [1.0, 9.0]


def test_registry_upsert_diger_serileri_korur(data_root):
    save_series(make_meta(name="a"), make_df(["2024-01-01"], [1.0], series_id="a"))
    save_series(make_meta(name="b"), make_df(["2024-01-01"], [2.0], series_id="b"))
    save_series(
        make_meta(name="a", url="https://example.org/yeni"),
        make_df(["2024-01-01"], [1.1], series_id="a"),
    )

    reg = registry()
    assert set(reg) == {"a", "b"}
    assert reg["a"]["url"] == "https://example.org/yeni"
    assert reg["b"]["url"] == "https://example.org/veri.csv"


def test_farkli_series_id_ayni_tarih_cokmez(data_root):
    # Long-format df'te aynı tarihte iki farklı seri varsa ikisi de kalmalı;
    # date-bazlı tekilleştirme bunları sessizce çökertirdi (denetçi bulgusu).
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "value": [1.0, 2.0],
            "series_id": ["kod_a", "kod_b"],
        }
    )
    save_series(make_meta(), df)

    out = load_series("test_serisi")
    assert len(out) == 2
    assert out.loc[out["series_id"] == "kod_a", "value"].tolist() == [1.0]
    assert out.loc[out["series_id"] == "kod_b", "value"].tolist() == [2.0]


def test_coklu_seri_upsertte_son_deger_kalir(data_root):
    # İki serilik upsert: revize değer (kod_a@Ocak) eskiyi ezmeli,
    # diğer serinin o günkü değeri (kod_b@Ocak) kaybolmamalı.
    save_series(
        make_meta(),
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
                "value": [1.0, 2.0],
                "series_id": ["kod_a", "kod_b"],
            }
        ),
    )
    save_series(
        make_meta(),
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
                "value": [1.5, 2.5],
                "series_id": ["kod_a", "kod_b"],
            }
        ),
    )

    out = load_series("test_serisi")
    assert len(out) == 3
    assert out.loc[out["series_id"] == "kod_a", "value"].tolist() == [1.5]
    assert out.loc[out["series_id"] == "kod_b", "value"].tolist() == [2.0, 2.5]


def test_load_olmayan_seri_keyerror(data_root):
    with pytest.raises(KeyError):
        load_series("olmayan_seri")


def test_eksik_sutun_valueerror(data_root):
    df = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "value": [1.0]})
    with pytest.raises(ValueError, match="series_id"):
        save_series(make_meta(), df)


def test_gecersiz_frekans_valueerror():
    with pytest.raises(ValueError, match="frekans"):
        make_meta(frequency="haftalık")
