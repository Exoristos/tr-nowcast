"""T7 fetch komutu testleri — kaynaklar monkeypatch'li, tamamen offline.

fetch_all sahteleri gerçek save_series'i çağırır; böylece fetch → status →
quality zinciri uçtan uca, ağa çıkmadan doğrulanır. status/quality testleri
test_cli_durum.py'dedir; ortak yardımcılar cli_test_araclari.py'dedir.
"""

from __future__ import annotations

import pandas as pd
import pytest
from cli_test_araclari import hata, kaynak_sahtesi
from click.testing import CliRunner

from trnowcast import store
from trnowcast.backtest import ForecastPoint
from trnowcast.cli import main
from trnowcast.models import MODELS
from trnowcast.scoring import HEDEF_SERI, skor_yolu
from trnowcast.sources import evds, fao, fred, survey, tuik
from trnowcast.store import SeriesMeta, save_series


@pytest.fixture(autouse=True)
def _tmp_depo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path)


@pytest.fixture()
def kosucu():
    return CliRunner()


def test_fetch_all_basarili_ve_anahtarsiz_evds_bilgilendirilir(kosucu, monkeypatch):
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    monkeypatch.setattr(fred, "fetch_all", kaynak_sahtesi("sahte_fred"))
    monkeypatch.setattr(fao, "fetch_all", kaynak_sahtesi("sahte_fao"))
    monkeypatch.setattr(tuik, "fetch_all", kaynak_sahtesi("sahte_tuik"))

    sonuc = kosucu.invoke(main, ["fetch", "--source", "all"])

    assert sonuc.exit_code == 0, sonuc.output
    assert "[OK] fred: 1 seri kaydedildi" in sonuc.output
    assert "[OK] fao" in sonuc.output
    assert "[OK] tuik" in sonuc.output
    assert "EVDS_API_KEY" in sonuc.output  # bilgilendirme, traceback değil
    assert "[HATA]" not in sonuc.output


def test_fetch_evds_anahtarsiz_hicbir_evds_cagrisi_yapilmaz(kosucu, monkeypatch):
    cagrildi: list[str] = []
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    monkeypatch.setattr(evds, "fetch_all", lambda a: cagrildi.append("evds") or [])
    monkeypatch.setattr(survey, "fetch_all", lambda a: cagrildi.append("anket") or [])

    sonuc = kosucu.invoke(main, ["fetch", "--source", "evds"])

    # anahtar-yok atlaması başarısızlık sayılmaz: graceful skip → exit 0
    assert sonuc.exit_code == 0, sonuc.output
    assert "EVDS_API_KEY" in sonuc.output
    assert cagrildi == []


def test_fetch_anahtarla_evds_ve_anket_cagrilir(kosucu, monkeypatch):
    gelen: dict[str, str] = {}

    def sahte_evds(anahtar):
        gelen["evds"] = anahtar
        return [store.DATA_ROOT / "processed" / "usd_try_gunluk.parquet"]

    def sahte_anket(anahtar):
        gelen["anket"] = anahtar
        return [store.DATA_ROOT / "processed" / "tufe_beklenti_pka.parquet"]

    monkeypatch.setenv("EVDS_API_KEY", "test-anahtar-123")
    monkeypatch.setattr(evds, "fetch_all", sahte_evds)
    monkeypatch.setattr(survey, "fetch_all", sahte_anket)

    sonuc = kosucu.invoke(main, ["fetch", "--source", "evds"])

    assert sonuc.exit_code == 0, sonuc.output
    assert "[OK] evds" in sonuc.output
    assert "[OK] anket" in sonuc.output
    assert gelen == {"evds": "test-anahtar-123", "anket": "test-anahtar-123"}


def test_fetch_kaynak_hatasi_atlanir_exit_0(kosucu, monkeypatch):
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    monkeypatch.setattr(fred, "fetch_all", hata("FRED ağ hatası (test)"))
    monkeypatch.setattr(fao, "fetch_all", kaynak_sahtesi("sahte_fao"))
    monkeypatch.setattr(tuik, "fetch_all", kaynak_sahtesi("sahte_tuik"))

    sonuc = kosucu.invoke(main, ["fetch", "--source", "all"])

    assert sonuc.exit_code == 0, sonuc.output
    assert "[HATA] fred: FRED ağ hatası (test)" in sonuc.output
    assert "[OK] fao" in sonuc.output
    assert "[OK] tuik" in sonuc.output


def test_fetch_denenen_tum_kaynaklar_basarisizsa_exit_1(kosucu, monkeypatch):
    monkeypatch.setattr(fred, "fetch_all", hata("ağ yok (test)"))

    sonuc = kosucu.invoke(main, ["fetch", "--source", "fred"])

    assert sonuc.exit_code == 1
    assert "Tüm kaynaklar başarısız" in sonuc.output


def test_fetch_status_quality_uctan_uca_birlesir(kosucu, monkeypatch):
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    monkeypatch.setattr(fred, "fetch_all", kaynak_sahtesi("birlesme_fred"))
    monkeypatch.setattr(fao, "fetch_all", kaynak_sahtesi("birlesme_fao"))
    monkeypatch.setattr(tuik, "fetch_all", kaynak_sahtesi("birlesme_tuik"))

    fetch_s = kosucu.invoke(main, ["fetch", "--source", "all"])
    assert fetch_s.exit_code == 0, fetch_s.output
    for ad in ("birlesme_fred", "birlesme_fao", "birlesme_tuik"):
        assert len(store.load_series(ad)) == 2  # depoya gerçekten yazıldı

    status_s = kosucu.invoke(main, ["status"])
    assert status_s.exit_code == 0, status_s.output
    assert "birlesme_fred" in status_s.output
    assert "TestKaynak" in status_s.output  # kaynak sütunu
    assert "2026-02-01" in status_s.output  # son değer tarihi
    assert "2026-01-01" not in status_s.output  # yalnız son değer gösterilir

    quality_s = kosucu.invoke(main, ["quality"])
    assert quality_s.exit_code == 0, quality_s.output
    assert "[HATA]" not in quality_s.output


# --- T19: backtest --models seçimi --------------------------------------------
# Tam arena 8 yarışmacı; TSFM'ler (chronos2_uni, timesfm3_mv) ağırlık/GPU
# istediğinden testte sahte ModelFn ile değiştirilir (plan T19 Step 1).

ARENA = {
    "naive",
    "seasonal_naive",
    "arima",
    "ets",
    "chronos2_uni",
    "timesfm3_mv",
    "bridge",
    "anket_pka",
}
KLASIKLER = {"naive", "seasonal_naive", "arima", "ets"}


def _tsfm_sahtesi(model_adi: str):
    def sahte(kesit, hedef_ay, target):
        return ForecastPoint(
            target_month=hedef_ay, point=10.0, lower=8.0, upper=12.0, model=model_adi
        )

    return sahte


@pytest.fixture()
def tsfm_sahte(monkeypatch):
    for ad in ("chronos2_uni", "timesfm3_mv"):
        monkeypatch.setitem(MODELS, ad, _tsfm_sahtesi(ad))


@pytest.fixture()
def tufe_kayitli():
    aylar = pd.period_range("2017-01", "2021-04", freq="M")
    degerler = [10.0 + 0.1 * i + (0.5 if i % 2 else -0.5) for i in range(len(aylar))]
    df = pd.DataFrame({"date": aylar.start_time, "value": degerler, "series_id": HEDEF_SERI})
    kayit = SeriesMeta(
        name=HEDEF_SERI,
        source="test",
        url="https://ornek.test/tufe.csv",
        frequency="aylık",
        units="% (aylık)",
        publication_lag_days=3,
        license_note="test kapsamı",
    )
    save_series(kayit, df)


def test_backtest_models_classic_yalniz_faz1_dortlusu(kosucu, tufe_kayitli):
    sonuc = kosucu.invoke(
        main, ["backtest", "--start", "2021-01", "--end", "2021-04", "--models", "classic"]
    )

    assert sonuc.exit_code == 0, sonuc.output
    skor = pd.read_parquet(skor_yolu())
    assert set(skor["model"]) == KLASIKLER
    assert "chronos2_uni" not in sonuc.output  # TSFM arenada yok


def test_backtest_models_all_8_model_tsfm_sahteyle(kosucu, tufe_kayitli, tsfm_sahte):
    sonuc = kosucu.invoke(
        main, ["backtest", "--start", "2021-01", "--end", "2021-04", "--models", "all"]
    )

    assert sonuc.exit_code == 0, sonuc.output
    skor = pd.read_parquet(skor_yolu())
    assert set(skor["model"]) == ARENA
    assert len(skor) == 32  # 8 model × 4 ay


def test_backtest_varsayilan_all(kosucu, tufe_kayitli, tsfm_sahte):
    sonuc = kosucu.invoke(main, ["backtest", "--start", "2021-01", "--end", "2021-04"])

    assert sonuc.exit_code == 0, sonuc.output
    skor = pd.read_parquet(skor_yolu())
    assert set(skor["model"]) == ARENA


def test_backtest_models_csv_listesi(kosucu, tufe_kayitli):
    sonuc = kosucu.invoke(
        main,
        ["backtest", "--start", "2021-01", "--end", "2021-04", "--models", "naive,bridge"],
    )

    assert sonuc.exit_code == 0, sonuc.output
    skor = pd.read_parquet(skor_yolu())
    assert set(skor["model"]) == {"naive", "bridge"}


def test_backtest_models_bilinmeyen_ad_hata(kosucu, tufe_kayitli):
    sonuc = kosucu.invoke(main, ["backtest", "--models", "naive,yok_boyle"])

    assert sonuc.exit_code != 0
    assert "bilinmeyen model" in sonuc.output
