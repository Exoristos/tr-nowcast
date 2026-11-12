"""T7 status ve quality komutu testleri — tamamen offline.

Ortak yardımcılar cli_test_araclari.py'dedir; fetch komutu testleri test_cli.py'dedir.
"""

from __future__ import annotations

import pandas as pd
import pytest
from cli_test_araclari import hata, kaydet, kaynak_sahtesi, seri_df
from click.testing import CliRunner

from trnowcast import store
from trnowcast.cli import main
from trnowcast.sources import evds, fao, fred, survey, tuik


@pytest.fixture(autouse=True)
def _tmp_depo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path)


@pytest.fixture()
def kosucu():
    return CliRunner()


# --- status: kalıcı fetch kaydından kaynak kırılma izi (denetçi bulgusu) ----


def test_status_kirilan_kaynagi_nedeniyleyle_gosterir(kosucu, monkeypatch):
    # RF1: TÜİK kırılır, o seri asla kayıt açılmaz; registry'de iz kalmaz ama
    # status, kırılan kaynağı ve nedenini kalıcı fetch kaydından göstermelidir
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    monkeypatch.setattr(fred, "fetch_all", kaynak_sahtesi("sahte_fred"))
    monkeypatch.setattr(fao, "fetch_all", kaynak_sahtesi("sahte_fao"))
    monkeypatch.setattr(tuik, "fetch_all", hata("TÜİK SDMX Bearer token istiyor"))

    fetch_s = kosucu.invoke(main, ["fetch", "--source", "all"])
    assert fetch_s.exit_code == 0, fetch_s.output

    status_s = kosucu.invoke(main, ["status"])
    assert status_s.exit_code == 0, status_s.output
    assert "kaynak durumu" in status_s.output
    assert "[HATA] tuik: TÜİK SDMX Bearer token istiyor" in status_s.output
    assert "[OK] fred" in status_s.output
    assert "[OK] fao" in status_s.output


def test_status_gecersiz_anahtarla_kirilma_gosterir(kosucu, monkeypatch):
    # anahtar VAR ama 401: _evds_anahtar_notu tetiklenmez; kırılma yine görünmeli
    monkeypatch.setenv("EVDS_API_KEY", "gecersiz")
    monkeypatch.setattr(
        evds, "fetch_all", hata("EVDS anahtarı geçersiz veya yetkisiz (HTTP 401)")
    )
    monkeypatch.setattr(
        survey, "fetch_all", hata("EVDS anahtarı geçersiz veya yetkisiz (HTTP 401)")
    )

    kosucu.invoke(main, ["fetch", "--source", "evds"])

    status_s = kosucu.invoke(main, ["status"])
    assert status_s.exit_code == 0, status_s.output
    assert "[HATA] evds: EVDS anahtarı geçersiz veya yetkisiz (HTTP 401)" in status_s.output
    assert "[HATA] anket" in status_s.output
    assert "[ATLANDI]" not in status_s.output


def test_status_anahtarsiz_atlamayi_kaydindan_gosterir(kosucu, monkeypatch):
    monkeypatch.delenv("EVDS_API_KEY", raising=False)

    kosucu.invoke(main, ["fetch", "--source", "evds"])

    status_s = kosucu.invoke(main, ["status"])
    assert status_s.exit_code == 0, status_s.output
    assert "[ATLANDI] evds: EVDS_API_KEY tanımsız" in status_s.output
    assert "[ATLANDI] anket" in status_s.output


# --- status: tablo ----------------------------------------------------------


def test_status_bos_registry_bilgilendirir(kosucu):
    sonuc = kosucu.invoke(main, ["status"])
    assert sonuc.exit_code == 0
    assert "Registry boş" in sonuc.output


def test_status_evds_anahtar_yoksa_not_duser(kosucu, monkeypatch):
    kaydet("sahte_fao")
    monkeypatch.delenv("EVDS_API_KEY", raising=False)

    yok_ken = kosucu.invoke(main, ["status"])
    assert yok_ken.exit_code == 0
    assert "EVDS_API_KEY" in yok_ken.output

    monkeypatch.setenv("EVDS_API_KEY", "var")
    varken = kosucu.invoke(main, ["status"])
    assert varken.exit_code == 0
    assert "not: EVDS" not in varken.output


def test_status_parquet_olmayani_cokertmez(kosucu):
    kaydet("sahte_fao")
    (store.DATA_ROOT / "processed" / "sahte_fao.parquet").unlink()

    sonuc = kosucu.invoke(main, ["status"])
    assert sonuc.exit_code == 0, sonuc.output
    assert "PARQUET YOK" in sonuc.output


# --- quality ----------------------------------------------------------------


def test_quality_yapisal_hata_exit_1(kosucu):
    kaydet("sahte_fao")
    tekrar = pd.concat(
        [
            seri_df("sahte_fao"),
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-01-01"]),
                    "value": [9.9],
                    "series_id": "sahte_fao",
                }
            ),
        ],
        ignore_index=True,
    )
    yol = store.DATA_ROOT / "processed" / "sahte_fao.parquet"
    tekrar.to_parquet(yol, index=False)

    sonuc = kosucu.invoke(main, ["quality"])

    assert sonuc.exit_code == 1
    assert "[HATA]" in sonuc.output


def test_quality_uyari_hard_fail_degil_exit_0(kosucu):
    kaydet("turkiye_tufe_aylik_yuzde", [25.0], warn_range=(-2.0, 20.0))

    sonuc = kosucu.invoke(main, ["quality"])

    assert sonuc.exit_code == 0, sonuc.output
    assert "[UYARI]" in sonuc.output
    assert "[HATA]" not in sonuc.output


def test_quality_bos_registry_bilgilendirir(kosucu):
    sonuc = kosucu.invoke(main, ["quality"])
    assert sonuc.exit_code == 0
    assert "Registry boş" in sonuc.output
