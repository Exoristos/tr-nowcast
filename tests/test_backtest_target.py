"""Motorun target aktarımı (denetçi bulgusu, T14) — ModelFn 3 argümanlı.

ModelFn = fn(kesit, hedef_ay, target): motor, run_backtest'e verilen hedef seri
adını modellere 3. argüman olarak iletir. Aksi halde baseline modeller kendi
varsayılanı ('turkiye_tufe_aylik_yuzde') ile başka serinin kesitini okur ve
skorlar yanlış serinin actual'ına karşı sessizce hesaplanır.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trnowcast import store
from trnowcast.backtest import ForecastPoint, run_backtest
from trnowcast.models.baseline import naive
from trnowcast.store import SeriesMeta, save_series


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


def make_meta(**overrides) -> SeriesMeta:
    defaults = {
        "name": "sahte_tufe",
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


def test_motor_hedef_serisini_modele_aktarir(data_root):
    # Motor 3. argümanı kendi target parametresinden verir.
    aylar = pd.period_range("2017-01", "2019-06", freq="M").start_time
    save_series(make_meta(name="sahte_tufe"), make_df(aylar, [1.0] * len(aylar), "sahte_tufe"))
    yakalanan = []

    def kayit_modeli(kesit, hedef_ay, target) -> ForecastPoint:
        yakalanan.append(target)
        son = float(kesit[target]["value"].iloc[-1])
        return ForecastPoint(hedef_ay, son, son - 1.0, son + 1.0, "kayit")

    run_backtest(
        {"kayit": kayit_modeli},
        "sahte_tufe",
        pd.Timestamp("2019-03-01"),
        pd.Timestamp("2019-03-01"),
    )
    assert yakalanan == ["sahte_tufe"]


def test_baseline_model_motorun_serdigini_kullanir_digerini_degil(data_root):
    # Regression: iki kayıtlı seri varken run_backtest hedef=sahte_tufe ise
    # naive sahte_tufe kesitinden tahmin üretmeli; diger_seri kesiti (999.0)
    # ya da varsayılan TÜFE serisi hiç kullanılmamalı.
    # Hedef ay 2019-02, cutoff 2019-03-02, lag 3 → kesitte son ay 2019-01 (35.0).
    degerler_hedef = [10.0 + i for i in range(27)]  # 2016-12..2019-02; son değer 36.0
    aylar = pd.period_range("2016-12", "2019-02", freq="M").start_time
    save_series(
        make_meta(name="sahte_tufe"),
        make_df(aylar, degerler_hedef, "sahte_tufe"),
    )
    save_series(
        make_meta(name="diger_seri"),
        make_df(aylar, [999.0] * 27, "diger_seri"),
    )

    sonuc = run_backtest(
        {"naive": naive},
        "sahte_tufe",
        pd.Timestamp("2019-02-01"),
        pd.Timestamp("2019-02-01"),
    )
    satir = sonuc.iloc[0]
    # naive, sahte_tufe kesitinin son değerini (2019-01 = 35.0) kullanır;
    # diger_seri kesiti veya varsayılan TÜFE serisi kullanılsaydı point
    # bambaşka (veya ModelFailure) olurdu.
    assert satir["point"] == pytest.approx(35.0)
    assert satir["abs_error"] == pytest.approx(1.0)
