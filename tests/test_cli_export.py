"""trnowcast export CLI'si — --assets-root bayrağı (denetçi bulgusu, T25).

Offline: taze işaret nowcast.json verilir (arena koşmaz); sentetik seri ve
skor parquet'i kurulur. Bayrak verildiğinde yazılan dosyalar aynı göreli
yapıyla hedef dizine de kopyalanmalı; verilmediğinde kopyalanmamalı.
"""

import json

import pandas as pd
import pytest
from click.testing import CliRunner
from nowcast_araclari import make_df, make_meta

from trnowcast import store
from trnowcast.cli import main
from trnowcast.nowcast import kesit_gunu
from trnowcast.scoring import HEDEF_SERI, save_scores
from trnowcast.store import save_series


@pytest.fixture(autouse=True)
def _tmp_depo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path)


@pytest.fixture()
def kosucu():
    return CliRunner()


def _depo_kur() -> None:
    """Beş site serisi + skor parquet'i + taze işaret nowcast (arena koşmasın)."""
    aylar = pd.period_range("2025-04", "2026-05", freq="M")
    save_series(
        make_meta(name=HEDEF_SERI), make_df(aylar, [1.0] * len(aylar), HEDEF_SERI)
    )
    for ad, deger in (("fao_gida_endeks", 120.0), ("tufe_beklenti_pka", 24.0)):
        save_series(
            make_meta(name=ad, publication_lag_days=0),
            make_df(aylar, [deger] * len(aylar), ad),
        )
    for ad, deger in (("usd_try_gunluk", 38.0), ("brent_gunluk", 80.0)):
        gunler = pd.bdate_range("2026-03-02", "2026-06-10")
        save_series(
            make_meta(name=ad, frequency="günlük", publication_lag_days=0),
            make_df(gunler, [deger] * len(gunler), ad),
        )
    save_scores(
        pd.DataFrame(
            {
                "model": ["a", "a", "b", "b"],
                "target_month": pd.to_datetime(
                    ["2026-04-01", "2026-05-01", "2026-04-01", "2026-05-01"]
                ),
                "point": [1.0, 1.1, 0.9, 1.0],
                "lower": [0.0, 0.1, -0.1, 0.0],
                "upper": [2.0, 2.1, 1.9, 2.0],
                "actual": [1.0, 1.0, 1.0, 1.0],
                "abs_error": [0.0, 0.1, 0.1, 0.0],
                "hit80": [True, True, True, True],
            }
        )
    )
    isaret = {
        "generated_at": "2026-06-15",
        "cutoff_date": kesit_gunu(),  # bugün: _nowcast_bolumu taze sayar
        "target_month": "2026-06",
        "forecasts": [],
        "yillik": None,
    }
    yol = store.DATA_ROOT / "processed" / "nowcast.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(isaret), encoding="utf-8")


def test_export_assets_root_bayragi_kopyalar(kosucu):
    _depo_kur()
    kopya = store.DATA_ROOT / "assets_root"
    sonuc = kosucu.invoke(main, ["export", "--assets-root", str(kopya)])

    assert sonuc.exit_code == 0, sonuc.output
    # T25 çıktıları kopyada da var: chart.json + 12 aylık gerçek özet alanları.
    assert (kopya / "chart.json").is_file()
    assert (kopya / "series" / "tufe_aylik.json").is_file()
    skor = json.loads((kopya / "scores.json").read_text(encoding="utf-8"))
    assert {"median_mae_12m", "yon_isabet_12m", "bant_icinde_12m"} <= set(skor)


def test_export_varsayilan_assets_root_kopyalamaz(kosucu):
    _depo_kur()
    sonuc = kosucu.invoke(main, ["export"])

    assert sonuc.exit_code == 0, sonuc.output
    assert (store.DATA_ROOT / "site" / "chart.json").is_file()
