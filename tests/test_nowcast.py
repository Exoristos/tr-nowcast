"""nowcast (T20) birim testleri — tamamen offline; veri kökü tmp_path'e taşınır.

Review Focus kapsamı:
1. Cutoff dürüstlüğü: kesit ``asof_monthly(seri, cutoff=bugün)`` ile kurulur —
   backtest motorunun AYNI fonksiyonu; ayrı/gevşek kesit yolu yok. Hedef ay
   seride hâlâ yok (açıklanmamış).
2. Yıllık türetme: kümülatif formülün elle hesapla birebir eşitliği; 11'den az
   gerçek ay → ``yillik: null`` (uydurma yok).
+ Çıktı şeması, ModelFailure (ok:false), TÜFE güncelse hedef sonraki ay.
"""

import pandas as pd
import pytest
from nowcast_araclari import SABIT_AN, make_df, make_meta, tufe_serisi_kaydet

from trnowcast import store
from trnowcast.backtest import ForecastPoint, ModelFailure, asof_monthly
from trnowcast.nowcast import nowcast_kos
from trnowcast.scoring import HEDEF_SERI
from trnowcast.store import load_series, save_series


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    return root


@pytest.fixture
def sabit_an(monkeypatch):
    """nowcast koşum anını SABIT_AN'a sabitler; generated_at/cutoff_date deterministik olur."""
    monkeypatch.setattr("trnowcast.nowcast._simdi", lambda: SABIT_AN)
    return SABIT_AN


@pytest.fixture
def tufe_seri(data_root):
    tufe_serisi_kaydet()


def spy_model(kayit: dict):
    """Kesiti ve hedef ayı kaydeden sahte ModelFn — motorun beslediği kesiti yakalar."""

    def spy(kesit, hedef_ay, target):
        kayit["kesit"] = kesit
        kayit["hedef_ay"] = hedef_ay
        return ForecastPoint(hedef_ay, 1.0, 0.0, 2.0, "spy")

    return spy


def sabit_model(p: float):
    def fn(kesit, hedef_ay, target):
        return ForecastPoint(hedef_ay, p, p - 1.0, p + 1.0, "sabit")

    return fn


# --- Review Focus 1: cutoff dürüstlüğü --------------------------------------


def test_kesit_asof_monthly_cutoff_bugun(data_root, tufe_seri, sabit_an):
    kayit: dict = {}
    sonuc = nowcast_kos({"spy": spy_model(kayit)})
    # cutoff_date, motorun kesit kurarken kullandığı günün birebir aynısı.
    assert sonuc["cutoff_date"] == "2026-06-15"
    beklenen = asof_monthly(HEDEF_SERI, pd.Timestamp("2026-06-15"))
    pd.testing.assert_frame_equal(kayit["kesit"][HEDEF_SERI], beklenen)
    # Hedef ay: son değer (2026-05) → sonraki ilk ay.
    assert kayit["hedef_ay"] == pd.Timestamp("2026-06-01")
    assert sonuc["target_month"] == "2026-06"


def test_hedef_ay_seride_henuz_yok(data_root, tufe_seri, sabit_an):
    sonuc = nowcast_kos({"spy": spy_model({})})
    seri_aylari = set(load_series(HEDEF_SERI)["date"].dt.to_period("M"))
    assert pd.Period(sonuc["target_month"], freq="M") not in seri_aylari


def test_tufe_guncelse_hedef_sonraki_ay(data_root, tufe_seri, sabit_an):
    # "Bu ay zaten açıklanmış" senaryosu: son değer koşum ayında → hedef sonraki ay.
    save_series(
        make_meta(name=HEDEF_SERI),
        make_df([pd.Timestamp("2026-06-01")], [0.9], HEDEF_SERI),
    )
    sonuc = nowcast_kos({"spy": spy_model({})})
    assert sonuc["target_month"] == "2026-07"


# --- Review Focus 2: yıllık türetme ------------------------------------------


def test_yillik_kumulatif_formul_elle_hesap(data_root, tufe_seri, sabit_an):
    # Son 11 gerçek ayın hepsi %1.0; spy tahmini %1.0 (bant 0–2) →
    # elle: (1.01^11 · (1+t/100) − 1)·100, üç uç için aynı formül.
    sonuc = nowcast_kos({"spy": spy_model({})})
    y = sonuc["yillik"]
    assert y is not None
    assert y["point"] == pytest.approx((1.01**11 * 1.01 - 1) * 100)
    assert y["lower"] == pytest.approx((1.01**11 * 1.00 - 1) * 100)
    assert y["upper"] == pytest.approx((1.01**11 * 1.02 - 1) * 100)
    assert y["temel"] == "son 11 gerçek ay + hedef tahmini"


def test_yillik_coklu_modelde_medyandan(data_root, tufe_seri, sabit_an):
    sonuc = nowcast_kos({"a": sabit_model(0.5), "b": sabit_model(1.5)})
    # Medyan nokta %1.0 → elle: (1.01^11 · 1.01 − 1)·100.
    assert sonuc["yillik"]["point"] == pytest.approx((1.01**11 * 1.01 - 1) * 100)


def test_yillik_11_aydan_az_gercek_null(data_root, sabit_an):
    aylar = pd.period_range("2025-08", "2026-05", freq="M")  # yalnız 10 gerçek ay
    save_series(make_meta(name=HEDEF_SERI), make_df(aylar, [1.0] * len(aylar), HEDEF_SERI))
    sonuc = nowcast_kos({"spy": spy_model({})})
    assert sonuc["yillik"] is None


# --- Çıktı şeması + ModelFailure ---------------------------------------------


def test_cikti_semasi(data_root, tufe_seri, sabit_an):
    sonuc = nowcast_kos({"spy": spy_model({})})
    assert list(sonuc) == [
        "generated_at",
        "cutoff_date",
        "target_month",
        "forecasts",
        "yillik",
    ]
    assert sonuc["generated_at"] == "2026-06-15"  # ISO gün damgası (idempotentlik)
    assert len(sonuc["forecasts"]) == 1
    satir = sonuc["forecasts"][0]
    assert list(satir) == ["model", "point", "lower", "upper", "ok", "error"]
    assert satir["model"] == "spy"
    assert satir["ok"] is True
    assert satir["error"] is None
    assert satir["point"] == pytest.approx(1.0)


def test_model_failure_ok_false_ve_devam(data_root, tufe_seri, sabit_an):
    def coken_model(kesit, hedef_ay, target):
        raise ModelFailure("yakınsama yok")

    sonuc = nowcast_kos({"coken": coken_model, "saglam": sabit_model(1.0)})
    coken_satir, saglam_satir = sonuc["forecasts"]
    assert coken_satir["model"] == "coken"
    assert coken_satir["ok"] is False
    assert coken_satir["error"] == "yakınsama yok"
    assert coken_satir["point"] is None
    assert coken_satir["lower"] is None
    assert coken_satir["upper"] is None
    assert saglam_satir["ok"] is True
    # Saglam model olduğu için yıllık yine türetilir.
    assert sonuc["yillik"] is not None


def test_model_yukleme_hatasi_da_ok_false(data_root, tufe_seri, sabit_an):
    # timesfm adapter'ı yükleme hatasını try DIŞINDA ham exception olarak
    # fırlatır (tsfm_timesfm.py — Faz 2 kararına dokunulmaz); T20 sözleşmesi
    # gereği nowcast bunu da model başına ok:false'a çevirir, süreç çökmez.
    def yukleme_hatasi(kesit, hedef_ay, target):
        raise RuntimeError("HF ağırlık indirme başarısız: bağlantı yok")

    sonuc = nowcast_kos({"yukleme": yukleme_hatasi, "saglam": sabit_model(1.0)})
    hata_satiri, saglam_satir = sonuc["forecasts"]
    assert hata_satiri["ok"] is False
    assert "HF ağırlık indirme başarısız" in hata_satiri["error"]
    assert hata_satiri["point"] is None
    assert saglam_satir["ok"] is True
