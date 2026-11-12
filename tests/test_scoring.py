"""scoring (T14) testleri — summarize pencereleri, parquet kalıcılığı, backtest CLI.

Tamamen offline: veri kökü tmp_path'e taşınır, hedef seri sahte kayıtlıdır.
Review Focus 5 (pencere sabitliği) burada: "son 24 ay" verinin son ayına göre
kaydırılır, koşu tarihine bağlı değildir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from trnowcast import store
from trnowcast.cli import main
from trnowcast.scoring import (
    HEDEF_SERI,
    KOLONLAR,
    PENCERE_SON24,
    PENCERE_TAM,
    PENCERE_YENI,
    PENCERELER,
    SKOR_PARQUET_ADI,
    save_scores,
    skor_yolu,
    summarize,
)
from trnowcast.store import SeriesMeta, save_series


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


def satir(model: str, ay: str, hata: float | None, hit: bool | None = None) -> dict:
    """run_backtest çıktısı biçiminde tek satır; hata=None → başarısız (NaN) satır."""
    if hata is None:
        nanlar = {k: np.nan for k in ("point", "lower", "upper", "actual", "abs_error", "hit80")}
        return {"model": model, "target_month": pd.Timestamp(ay), **nanlar}
    return {
        "model": model,
        "target_month": pd.Timestamp(ay),
        "point": 1.0,
        "lower": 0.0,
        "upper": 2.0,
        "actual": 1.0 + hata,
        "abs_error": hata,
        "hit80": hit,
    }


# --- summarize: NaN dışlama + n_failed ---------------------------------------


def test_summarize_nan_disarida_n_failed_ayri():
    df = pd.DataFrame(
        [
            satir("a", "2019-01-01", 1.0, True),
            satir("a", "2019-02-01", 3.0, False),
            satir("a", "2019-03-01", None),  # ModelFailure
            satir("b", "2019-01-01", None),  # tamamen çöken model
            satir("b", "2019-02-01", None),
        ]
    )
    tablo = summarize(df).set_index(["model", "window"])

    a = tablo.loc[("a", PENCERE_TAM)]
    assert a["n"] == 2
    assert a["n_failed"] == 1
    assert a["mae"] == pytest.approx(2.0)
    assert a["rmse"] == pytest.approx(np.sqrt(5.0))
    assert a["hit80_rate"] == pytest.approx(0.5)

    b = tablo.loc[("b", PENCERE_TAM)]
    assert b["n"] == 0
    assert b["n_failed"] == 2
    assert pd.isna(b["mae"])
    assert pd.isna(b["rmse"])
    assert pd.isna(b["hit80_rate"])


def test_summarize_pencere_filtreleri():
    # max = 2020-06 → son-24 penceresi 2018-07'den başlar: 2018-10 SATIRI içerde,
    # ama 2019→bugün penceresi onu dışarıda bırakır; tam geçmiş üçünü de alır.
    df = pd.DataFrame(
        [
            satir("a", "2018-10-01", 1.0, True),
            satir("a", "2019-01-01", 1.0, True),
            satir("a", "2020-06-01", 1.0, True),
        ]
    )
    tablo = summarize(df).set_index(["model", "window"])

    assert tablo.loc[("a", PENCERE_YENI), "n"] == 2
    assert tablo.loc[("a", PENCERE_SON24), "n"] == 3
    assert tablo.loc[("a", PENCERE_TAM), "n"] == 3
    # Pencere satır sırası sabit: her model için üç pencere tanımlı sırada.
    assert list(PENCERELER) == [PENCERE_YENI, PENCERE_SON24, PENCERE_TAM]


def test_summarize_son24_veriye_bagli_kosu_tarihine_degil():
    # Review Focus 5: aynı göreli konumdaki aylar (max-25 dışarıda, max-23 içerde,
    # max içerde) veri +12 ay kaydırılınca da AYNI üyelikte kalmalı.
    def kaydir_ile(aylar):
        return pd.DataFrame([satir("a", ay, 1.0, True) for ay in aylar])

    temel = kaydir_ile(["2019-11-01", "2020-01-01", "2021-12-01"])  # max 2021-12
    kaydirilmis = kaydir_ile(["2020-11-01", "2021-01-01", "2022-12-01"])  # max 2022-12

    def son24_aylar(df):
        tablo = summarize(df).set_index(["model", "window"])
        return tablo.loc[("a", PENCERE_SON24), "n"]

    assert son24_aylar(temel) == 2  # 2019-11 dışarıda (max-25), diğer ikisi içerde
    assert son24_aylar(kaydirilmis) == 2  # 2020-11 dışarıda (max-25), aynı üyelik


def test_summarize_bos_df_bos_tablo():
    tablo = summarize(pd.DataFrame(columns=KOLONLAR))
    assert tablo.empty
    assert list(tablo.columns) == ["model", "window", "mae", "rmse", "n", "n_failed", "hit80_rate"]


# --- save_scores: parquet kalıcılığı -----------------------------------------


def test_save_scores_yeni_yazar_ve_okunur(tmp_path):
    yol = tmp_path / "skor.parquet"
    df = pd.DataFrame([satir("a", "2019-01-01", 1.0, True), satir("a", "2019-02-01", None)])
    save_scores(df, yol)

    geri = pd.read_parquet(yol)
    assert len(geri) == 2
    assert list(geri.columns) == KOLONLAR
    assert geri["abs_error"].iloc[0] == pytest.approx(1.0)
    assert geri["hit80"].iloc[0]
    assert pd.isna(geri["abs_error"].iloc[1])


def test_save_scores_uzerine_tekillestirir(tmp_path):
    # Aynı (model, target_month) yeni koşumda değiştiyse yenisi kazanır; dokunulmayan
    # eski satırlar (2019-01 ve b modeli) korunur.
    yol = tmp_path / "skor.parquet"
    save_scores(
        pd.DataFrame(
            [satir("a", "2019-01-01", 1.0, True), satir("a", "2019-02-01", 2.0, True),
             satir("b", "2019-01-01", 5.0, True)]
        ),
        yol,
    )
    save_scores(
        pd.DataFrame([satir("a", "2019-02-01", 9.0, False), satir("a", "2019-03-01", 4.0, True)]),
        yol,
    )

    geri = pd.read_parquet(yol).set_index(["model", "target_month"])
    assert len(geri) == 4
    assert geri.loc[("a", pd.Timestamp("2019-01-01")), "abs_error"] == pytest.approx(1.0)
    assert geri.loc[("a", pd.Timestamp("2019-02-01")), "abs_error"] == pytest.approx(9.0)
    assert geri.loc[("a", pd.Timestamp("2019-03-01")), "abs_error"] == pytest.approx(4.0)
    assert geri.loc[("b", pd.Timestamp("2019-01-01")), "abs_error"] == pytest.approx(5.0)


def test_skor_yolu_islenmis_altinda(data_root):
    assert skor_yolu() == data_root / "processed" / SKOR_PARQUET_ADI


# --- backtest CLI -------------------------------------------------------------


def make_meta() -> SeriesMeta:
    return SeriesMeta(
        name=HEDEF_SERI,
        source="test",
        url="https://ornek.test/tufe.csv",
        frequency="aylık",
        units="yuzde",
        publication_lag_days=3,
        license_note="test kapsamı",
    )


@pytest.fixture
def tufe_kayitli(data_root):
    aylar = pd.period_range("2017-01", "2021-04", freq="M")
    degerler = [10.0 + 0.1 * i + (0.5 if i % 2 else -0.5) for i in range(len(aylar))]
    df = pd.DataFrame(
        {
            "date": aylar.start_time,
            "value": degerler,
            "series_id": HEDEF_SERI,
        }
    )
    save_series(make_meta(), df)


@pytest.fixture
def kosucu():
    return CliRunner()


def test_cli_backtest_tablo_4_model_3_pencere(kosucu, tufe_kayitli):
    # --models classic: T19'dan beri varsayılan 8 modeldir; TSFM ağırlığı
    # indirmeden 4 klasik model davranışını burada sabitliyoruz.
    sonuc = kosucu.invoke(
        main, ["backtest", "--start", "2021-01", "--end", "2021-04", "--models", "classic"]
    )
    assert sonuc.exit_code == 0, sonuc.output

    # 4 model satırı × 3 pencere: pencere etiketleri model başına birer kez.
    assert sonuc.output.count(PENCERE_YENI) == 4
    assert sonuc.output.count(PENCERE_SON24) == 4
    assert sonuc.output.count(PENCERE_TAM) == 4
    assert "n_failed" in sonuc.output

    yol = skor_yolu()
    assert yol.exists()
    skor = pd.read_parquet(yol)
    assert len(skor) == 16  # 4 model × 4 ay
    assert set(skor["model"]) == {"naive", "seasonal_naive", "arima", "ets"}
    assert not skor.duplicated(["model", "target_month"]).any()


def test_cli_backtest_varsayilan_end_son_aylik_deger(kosucu, tufe_kayitli):
    # --end verilmezse bitiş = serideki son aylık değerin ayı (2021-04).
    sonuc = kosucu.invoke(main, ["backtest", "--start", "2021-03", "--models", "classic"])
    assert sonuc.exit_code == 0, sonuc.output

    skor = pd.read_parquet(skor_yolu())
    assert skor["target_month"].max() == pd.Timestamp("2021-04-01")


def test_cli_backtest_tekrar_kosum_dedup(kosucu, tufe_kayitli):
    args = ["backtest", "--start", "2021-01", "--end", "2021-04", "--models", "classic"]
    ilk = kosucu.invoke(main, args)
    ikinci = kosucu.invoke(main, args)
    assert ilk.exit_code == 0 and ikinci.exit_code == 0, ilk.output + ikinci.output

    skor = pd.read_parquet(skor_yolu())
    assert len(skor) == 16  # üzerine yazıldı, birikmedi
    assert not skor.duplicated(["model", "target_month"]).any()
