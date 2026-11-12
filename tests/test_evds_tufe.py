"""EVDS TÜFE serileri (T9) birim testleri — tamamen offline.

Fixture gerçek canlı yanıttan kaydedildi (modifiye edilmemiş):
- evds_tufe_endeks.json: TP.TUKFIY2025.GENEL, 2026-01-01..2026-11-05 penceresi
  (aylık seri; Tarih "YYYY-M" biçimi ve nokta ondalık canlıdan gelir).

fetch_all testleri gerçek T2 deposuyla tmp_path üzerinde çalışır; ağ sahtelenir.
Canlı testler `live` işaretli, EVDS_API_KEY yoksa atlanır.
"""

import json
import os
import socket
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from trnowcast import store
from trnowcast.sources import SourceError, evds

FIXTURE_DIR = Path(__file__).parent / "fixtures"
ENDEKS_KODU = "TP.TUKFIY2025.GENEL"


def _oku(dosya: str) -> dict:
    return json.loads((FIXTURE_DIR / dosya).read_text(encoding="utf-8"))


def _dns_sahtele(monkeypatch) -> None:
    monkeypatch.setattr(
        evds.socket,
        "getaddrinfo",
        lambda host, port, type=None: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def test_endeks_fixture_aylik_tarihlerle_parse():
    df = evds.parse_json(_oku("evds_tufe_endeks.json"), ENDEKS_KODU)

    assert list(df.columns) == ["date", "value", "series_id"]
    assert (df["series_id"] == ENDEKS_KODU).all()
    assert len(df) == 10  # 2026-1..2026-10, pencerede eksik gözlem yok
    # aylık seriler "YYYY-M" tarihle gelir ve ay-başına düşer
    assert df["date"].iloc[0] == pd.Timestamp("2026-01-01")
    assert df["date"].iloc[-1] == pd.Timestamp("2026-10-01")
    assert df["date"].is_monotonic_increasing
    assert df["value"].iloc[0] == pytest.approx(115.73)
    assert df["value"].iloc[-1] == pytest.approx(140.77)


def test_aylik_yuzde_turet_ilk_ay_duser_degerler_dogru():
    endeks = evds.parse_json(_oku("evds_tufe_endeks.json"), ENDEKS_KODU)
    df = evds._aylik_yuzde_turet(endeks)

    assert len(df) == 9  # ilk ayın önceki değeri yok → o satır düşer
    assert df["date"].iloc[0] == pd.Timestamp("2026-02-01")
    # elle hesaplanmış uç değerler: 119.16/115.73-1 ve 140.77/137.23-1
    assert df["value"].iloc[0] == pytest.approx(2.964, rel=1e-3)
    assert df["value"].iloc[-1] == pytest.approx(2.5795, rel=1e-3)
    # T7 kalite tablosuyla uyum: türetilen aylık % uyarı aralığına sığar
    assert df["value"].between(-2.0, 20.0).all()


def test_aylik_yuzde_turet_tek_gozlem_sourceerror():
    tek = pd.DataFrame(
        {"date": [pd.Timestamp("2026-01-01")], "value": [100.0], "series_id": ENDEKS_KODU}
    )
    with pytest.raises(SourceError, match="en az 2"):
        evds._aylik_yuzde_turet(tek)


def test_aylik_yuzde_turet_ay_boslugu_sourceerror():
    # ortada bir ay eksikse pozisyonel pct_change iki aylık değişimi aylık % diye yazar — yasak
    bosluklu = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01")],
            "value": [100.0, 110.0],
            "series_id": ENDEKS_KODU,
        }
    )
    with pytest.raises(SourceError, match="ay boşluğu"):
        evds._aylik_yuzde_turet(bosluklu)


def test_aylik_yuzde_turet_kopya_ay_sourceerror():
    # dilim sızıntısı / kopya ay: türetme çarpımı çift sayım yapardı — önce reddedilir
    kopya = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2026-01-01"),
                pd.Timestamp("2026-01-15"),  # aynı ay, farklı gün: period'a göre kopya
                pd.Timestamp("2026-02-01"),
            ],
            "value": [100.0, 101.0, 103.0],
            "series_id": ENDEKS_KODU,
        }
    )
    with pytest.raises(SourceError, match="kopya"):
        evds._aylik_yuzde_turet(kopya)


def test_parse_sonrasi_null_ay_turetmede_sourceerror():
    # parse_json null ayı "eksik gözlem" diye düşer (satır bazında doğru);
    # türetme artık oluşan ay boşluğunu yakalar — sessiz iki aylık değişim yasak
    payload = {
        "items": [
            {"Tarih": "2026-1", "TP_TUKFIY2025_GENEL": "115.73"},
            {"Tarih": "2026-2", "TP_TUKFIY2025_GENEL": None},
            {"Tarih": "2026-3", "TP_TUKFIY2025_GENEL": "119.16"},
        ]
    }
    endeks = evds.parse_json(payload, ENDEKS_KODU)
    assert len(endeks) == 2
    with pytest.raises(SourceError, match="ay boşluğu"):
        evds._aylik_yuzde_turet(endeks)


def test_fetch_all_uc_seri_depoya_yazar(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path / "data")
    cekilen: list[str] = []

    def _sahte_get(self, series, start, end):
        cekilen.append(series)
        assert start == evds._FETCH_BASLANGICI
        if series == "TP.DK.USD.S.YTL":
            return evds.parse_json(_oku("evds_usdtry.json"), series)
        assert series == ENDEKS_KODU
        return evds.parse_json(_oku("evds_tufe_endeks.json"), series)

    monkeypatch.setattr(evds.EvdsClient, "get", _sahte_get)
    yollar = evds.fetch_all("test-anahtar")

    # türetilen seri ayrı ağ çağrısı yapmaz: kod başına tek istek (aylık % cache'ten)
    assert cekilen == ["TP.DK.USD.S.YTL", ENDEKS_KODU]
    assert len(yollar) == 3
    assert {y.name for y in yollar} == {
        "usd_try_gunluk.parquet",
        "turkiye_tufe_endeks.parquet",
        "turkiye_tufe_aylik_yuzde.parquet",
    }

    kayit = store.registry()
    assert kayit["turkiye_tufe_endeks"]["frequency"] == "aylık"
    assert kayit["turkiye_tufe_endeks"]["units"] == "Endeks (2025=100)"
    assert kayit["turkiye_tufe_endeks"]["publication_lag_days"] == 3
    assert kayit["turkiye_tufe_aylik_yuzde"]["units"] == "% (aylık, türetilmiş)"
    assert f"series={ENDEKS_KODU}" in kayit["turkiye_tufe_endeks"]["url"]
    # günlük serinin meta sözleşmesi (T6'dan taşınan iddialar — denetçi bulgusu 2)
    usd_meta = kayit["usd_try_gunluk"]
    assert usd_meta["source"] == "TCMB EVDS"
    assert usd_meta["frequency"] == "günlük"
    assert usd_meta["publication_lag_days"] == 1
    assert "series=TP.DK.USD.S.YTL" in usd_meta["url"]

    endeks = store.load_series("turkiye_tufe_endeks")
    assert (endeks["series_id"] == "turkiye_tufe_endeks").all()
    assert (endeks["date"].dt.day == 1).all()  # ortak şema: aylık → ay-başı
    yuzde = store.load_series("turkiye_tufe_aylik_yuzde")
    assert len(yuzde) == 9
    assert yuzde["value"].iloc[-1] == pytest.approx(2.5795, rel=1e-3)
    usd = store.load_series("usd_try_gunluk")
    assert len(usd) == 5
    assert (usd["series_id"] == "usd_try_gunluk").all()


# EvdsClient.get dilimleme (denetim bulgusu 1: EVDS yanıt başına ≤1000 gözlem döndürür
# ve fazlasını baştan sessiz kırpar — uzun pencere dilimlere bölünmeli)


def test_get_uzun_pencere_dilimlere_bolunur(monkeypatch):
    _dns_sahtele(monkeypatch)
    istekler: list[str] = []

    def _sahte_get(url, headers=None, timeout=None, allow_redirects=None, **_):
        istekler.append(url)
        yanit = SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"items": [{"Tarih": "01-01-2010", "TP_DK_USD_S_YTL": "1,0"}]},
        )
        return yanit

    monkeypatch.setattr(evds.requests, "get", _sahte_get)
    # 901 kapsayıcı gün: 900 günlük dilimlere bölünür (dilim ≤900 satır < 1000 sınırı)
    df = evds.EvdsClient("anahtar").get("TP.DK.USD.S.YTL", date(2010, 1, 1), date(2012, 6, 19))

    assert len(istekler) == 2
    assert "startDate=01-01-2010&endDate=18-06-2012" in istekler[0]
    assert "startDate=19-06-2012&endDate=19-06-2012" in istekler[1]
    # T11: iki dilim yanıtı tek çerçevede birleşti; iki yanıt da aynı satırı
    # (birebir eşit) döndürdüğü için meşru dilim örtüşmesi tek satıra düşer
    assert len(df) == 1


def test_get_sinir_dolu_yanit_sourceerror(monkeypatch):
    """Sınırı dolduran (1000 satır) dilim yanıtı SourceError'dır — sessiz kırpılma yasak."""
    _dns_sahtele(monkeypatch)
    dolu = {"items": [{"Tarih": "01-01-2010", "TP_DK_USD_S_YTL": "1"}] * evds._YANIT_SINIRI}
    monkeypatch.setattr(
        evds.requests,
        "get",
        lambda url, **_: SimpleNamespace(status_code=200, text="", json=lambda: dolu),
    )
    with pytest.raises(SourceError, match="kırpılma"):
        evds.EvdsClient("anahtar").get("TP.DK.USD.S.YTL", date(2010, 1, 1), date(2012, 6, 17))


# canlı


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("EVDS_API_KEY"), reason="EVDS_API_KEY yok")
def test_live_tufe_endeks_buguneakiyor():
    client = evds.EvdsClient(os.environ["EVDS_API_KEY"])
    df = client.get(ENDEKS_KODU, date(2025, 6, 1), date.today())
    assert len(df) > 0
    # 2026-11-05 canlı teyidi: seri 2026-10'a kadar akıyor
    assert df["date"].max() >= pd.Timestamp("2026-09-01")


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("EVDS_API_KEY"), reason="EVDS_API_KEY yok")
def test_live_tufe_aylik_yuzde_turetilmis_aralik():
    client = evds.EvdsClient(os.environ["EVDS_API_KEY"])
    endeks = client.get(ENDEKS_KODU, date(2025, 6, 1), date.today())
    df = evds._aylik_yuzde_turet(endeks)
    assert len(df) > 0
    assert df["value"].between(-2.0, 20.0).all()  # T7 uyarı aralığı [-2, 20]
