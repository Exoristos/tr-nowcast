"""export (T20) birim testleri — tamamen offline; veri kökü tmp_path'e taşınır.

Review Focus kapsamı:
3. Çöken model siteyi kırmaz: ``ok:false`` satırıyla JSON geçerli şemada kalır.
4. Idempotentlik: iki üst üste koşum aynı baytları üretir (CI commit gürültüsü önlenir).
+ Dosya seti, seri şeması (series/unit/points), scores/meta şemaları.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from nowcast_araclari import SABIT_AN, make_df, make_meta

import trnowcast.nowcast as nowcast_mod
from trnowcast import store
from trnowcast.backtest import ForecastPoint, ModelFailure
from trnowcast.export import export_site
from trnowcast.scoring import HEDEF_SERI, save_scores
from trnowcast.store import save_series


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


@pytest.fixture
def sabit_an(monkeypatch):
    """Koşum anını SABIT_AN'a sabitler; generated_at deterministik olur."""
    monkeypatch.setattr("trnowcast.nowcast._simdi", lambda: SABIT_AN)
    return SABIT_AN


def site_yolu() -> Path:
    # out_dir verilmediğinde varsayılan: store.DATA_ROOT / "site".
    return store.DATA_ROOT / "site"


@pytest.fixture
def site_verileri(data_root):
    """Beş site serisi + hedef seri + skor parquet'i içeren hazır depo."""
    aylar = pd.period_range("2025-04", "2026-05", freq="M")
    save_series(
        make_meta(name=HEDEF_SERI, units="% (aylık, türetilmiş)"),
        make_df(aylar, [1.0] * len(aylar), HEDEF_SERI),
    )
    save_series(
        make_meta(name="fao_gida_endeks"),
        make_df(aylar, [120.0] * len(aylar), "fao_gida_endeks"),
    )
    save_series(
        make_meta(name="tufe_beklenti_pka", publication_lag_days=0),
        make_df(aylar, [24.0] * len(aylar), "tufe_beklenti_pka"),
    )
    for ad, deger in (("usd_try_gunluk", 38.0), ("brent_gunluk", 80.0)):
        # İş günü serisi: ayda ~20-22 satır (tam takvim değil) + kısmi Haziran.
        gunler = pd.bdate_range("2026-03-02", "2026-06-10")
        save_series(
            make_meta(name=ad, frequency="günlük", publication_lag_days=0),
            make_df(gunler, [deger] * len(gunler), ad),
        )
    # Model "c" tamamen başarısız: mae/rmse/hit80 NaN → JSON'da null (NaN yasak).
    satirlar = pd.DataFrame(
        {
            "model": ["a", "a", "b", "b", "c", "c"],
            "target_month": pd.to_datetime(["2026-04-01", "2026-05-01"] * 3),
            "point": [1.0, 1.1, 0.9, 1.0, np.nan, np.nan],
            "lower": [0.0, 0.1, -0.1, 0.0, np.nan, np.nan],
            "upper": [2.0, 2.1, 1.9, 2.0, np.nan, np.nan],
            "actual": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            "abs_error": [0.0, 0.1, 0.1, 0.0, np.nan, np.nan],
            "hit80": [True, True, True, True, np.nan, np.nan],
        }
    )
    save_scores(satirlar)


@pytest.fixture
def sahte_model_arenasi(monkeypatch):
    """Gerçek arenayı (TSFM ağırlığı yok) tek sahte modelle değiştirir."""

    def saglam_model(kesit, hedef_ay, target):
        return ForecastPoint(hedef_ay, 1.0, 0.0, 2.0, "saglam")

    monkeypatch.setattr(nowcast_mod, "MODELS", {"saglam": saglam_model})


# _hashler ve idempotentlik testi test_export_chart.py'ye taşındı (T25 ile
# chart.json da kapsar; dosya 250 satır kuralı).


# --- Dosya seti ---------------------------------------------------------------


def test_dosya_seti(site_verileri, sahte_model_arenasi, sabit_an):
    yollar = export_site()
    site = site_yolu()
    beklenen = {
        "nowcast.json",
        "scores.json",
        "meta.json",
        "chart.json",
        "series/tufe_aylik.json",
        "series/usd_aylik.json",
        "series/brent_aylik.json",
        "series/fao_aylik.json",
        "series/anket_pka.json",
    }
    assert {str(y.relative_to(site)) for y in yollar} == beklenen
    for ad in beklenen:
        assert (site / ad).is_file()


# --- Seri şeması --------------------------------------------------------------


def test_seri_semasi(site_verileri, sahte_model_arenasi, sabit_an):
    export_site()
    tufe = json.loads((site_yolu() / "series/tufe_aylik.json").read_text(encoding="utf-8"))
    assert list(tufe) == ["series", "unit", "points"]
    assert tufe["series"] == HEDEF_SERI
    assert tufe["unit"] == "% (aylık, türetilmiş)"
    tarihler = [p[0] for p in tufe["points"]]
    assert tarihler == sorted(tarihler)
    assert tarihler[0] == "2025-04-01" and tarihler[-1] == "2026-05-01"
    assert all(isinstance(p[1], float) for p in tufe["points"])

    usd = json.loads((site_yolu() / "series/usd_aylik.json").read_text(encoding="utf-8"))
    # İş günü günlük serisi: bitmiş ayların ortalaması (Mart–Mayıs 2026);
    # kısmi Haziran ayı gösterime girmez.
    assert [p[0] for p in usd["points"]] == ["2026-03-01", "2026-04-01", "2026-05-01"]
    assert usd["points"][0][1] == pytest.approx(38.0)
    assert usd["unit"] == "yuzde"


# --- scores.json + meta.json --------------------------------------------------


def test_scores_semasi(site_verileri, sahte_model_arenasi, sabit_an):
    export_site()
    skor = json.loads((site_yolu() / "scores.json").read_text(encoding="utf-8"))
    assert skor["generated_at"] == "2026-06-15"
    assert skor["windows"] == ["2019→bugün", "son 24 ay", "tam geçmiş"]
    for s in skor["scores"]:
        assert set(s) == {"model", "window", "mae", "rmse", "n", "n_failed", "hit80_rate"}
    a = next(s for s in skor["scores"] if s["model"] == "a" and s["window"] == "tam geçmiş")
    assert a["n"] == 2 and a["n_failed"] == 0
    assert a["mae"] == pytest.approx(0.05)
    # Başarısız modelin NaN metrikleri null olarak çıkar; metin içinde NaN geçmez.
    c = next(s for s in skor["scores"] if s["model"] == "c" and s["window"] == "tam geçmiş")
    assert c["n"] == 0 and c["n_failed"] == 2
    assert c["mae"] is None and c["hit80_rate"] is None
    assert "NaN" not in (site_yolu() / "scores.json").read_text(encoding="utf-8")


def test_meta_registry_ve_generated_at(site_verileri, sahte_model_arenasi, sabit_an):
    export_site()
    meta = json.loads((site_yolu() / "meta.json").read_text(encoding="utf-8"))
    assert list(meta) == ["generated_at", "registry"]
    assert meta["generated_at"] == "2026-06-15"
    assert list(meta["registry"]) == sorted(meta["registry"])
    assert meta["registry"][HEDEF_SERI]["source"] == "test"


# --- Review Focus 3: çöken model siteyi kırmaz ---------------------------------


def test_coken_model_siteyi_kirmaz(site_verileri, sabit_an, monkeypatch):
    def coken_model(kesit, hedef_ay, target):
        raise ModelFailure("chronos CPU'da çöktü")

    def saglam_model(kesit, hedef_ay, target):
        return ForecastPoint(hedef_ay, 1.0, 0.0, 2.0, "saglam")

    monkeypatch.setattr(
        nowcast_mod, "MODELS", {"coken": coken_model, "saglam": saglam_model}
    )
    export_site()
    nc = json.loads((site_yolu() / "nowcast.json").read_text(encoding="utf-8"))
    assert list(nc) == [
        "generated_at",
        "cutoff_date",
        "target_month",
        "forecasts",
        "yillik",
    ]
    coken_satir = next(t for t in nc["forecasts"] if t["model"] == "coken")
    assert coken_satir["ok"] is False
    assert coken_satir["error"] == "chronos CPU'da çöktü"
    assert coken_satir["point"] is None
    # Saglam model var: yıllık yine türetilir, şema tam kalır.
    assert nc["yillik"] is not None


# --- nowcast.json yeniden kullanımı (denetçi: çift koşum + tutarlılık) ---------


def _isaret_nowcast(cutoff_gunu: str) -> dict:
    return {
        "generated_at": cutoff_gunu,
        "cutoff_date": cutoff_gunu,
        "target_month": "2026-06",
        "forecasts": [
            {
                "model": "isaret",
                "point": 9.9,
                "lower": 9.0,
                "upper": 10.0,
                "ok": True,
                "error": None,
            }
        ],
        "yillik": None,
    }


def test_export_mevcut_nowcast_json_kullanir(site_verileri, sabit_an, monkeypatch):
    # 'trnowcast nowcast'ın yazdığı TAZE kesit (cutoff_date = bugün) varsa
    # export arenayı yeniden koşturmaz: CI'da TSFM çıkarımı tek kez çalışır ve
    # data/processed + data/site nowcast.json'ları bit-bit tutarlı kalır.
    isaret = _isaret_nowcast("2026-06-15")
    yol = store.DATA_ROOT / "processed" / "nowcast.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(isaret), encoding="utf-8")

    def cagrilirsa_patla(kesit, hedef_ay, target):
        raise AssertionError("arena yeniden koşulmamalıydı")

    monkeypatch.setattr(nowcast_mod, "MODELS", {"patla": cagrilirsa_patla})
    export_site()
    nc = json.loads((site_yolu() / "nowcast.json").read_text(encoding="utf-8"))
    assert nc == isaret


def test_export_bayat_nowcast_json_yeniden_kosar(site_verileri, sahte_model_arenasi, sabit_an):
    # cutoff_date bugünden eskiyse depodaki dosya kullanılmaz — taze koşum yazılır.
    yol = store.DATA_ROOT / "processed" / "nowcast.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(_isaret_nowcast("2026-06-14")), encoding="utf-8")
    export_site()
    nc = json.loads((site_yolu() / "nowcast.json").read_text(encoding="utf-8"))
    assert nc["cutoff_date"] == "2026-06-15"
    assert nc["forecasts"][0]["point"] == pytest.approx(1.0)
