"""EVDS çekici (T6) birim testleri — tamamen offline.

Ağ sınırı (DNS + requests.get) sahtelenir; canlı çağrı `live` işaretli testte
yapılır ve anahtar yoksa atlanır. Anket testleri tests/test_survey.py'dadır.
"""

import json
import os
import socket
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from trnowcast.sources import SourceError, evds

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _oku(dosya: str) -> dict:
    return json.loads((FIXTURE_DIR / dosya).read_text(encoding="utf-8"))


@dataclass
class _SahteYanit:
    """requests.Response'nun yalnız evds._guvenli_cek'in kullandığı yüzeyi."""

    status_code: int = 200
    payload: dict | None = None
    text: str = ""

    def json(self):
        if self.payload is None:
            raise ValueError("gövde JSON değil")
        return self.payload


def _ag_sahtele(monkeypatch, yanitlar: list[_SahteYanit] | None = None):
    """DNS ve requests.get'i sahteler; yakalanan istek argümanlarını döndürür."""
    yakalanan: dict = {}

    def _sahte_addrinfo(host, port, type=None):
        yakalanan["host"] = host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(evds.socket, "getaddrinfo", _sahte_addrinfo)

    yanitlar = yanitlar or [_SahteYanit(payload=_oku("evds_usdtry.json"))]

    def _sahte_get(url, headers=None, timeout=None, allow_redirects=None, **_):
        yakalanan.update(url=url, headers=headers, allow_redirects=allow_redirects)
        return yanitlar.pop(0)

    monkeypatch.setattr(evds.requests, "get", _sahte_get)
    return yakalanan


# evds.parse_json


def test_series_sozlugu_planla_ayni():
    # T9: TÜFE ana boru EVDS'te; aylık % doğrudan seri yok, endeksten türetilir
    assert evds.SERIES == {
        "usd_try_gunluk": "TP.DK.USD.S.YTL",
        "turkiye_tufe_endeks": "TP.TUKFIY2025.GENEL",
        "turkiye_tufe_aylik_yuzde": "TP.TUKFIY2025.GENEL",
    }


def test_usdtry_fixture_long_format_semasi():
    df = evds.parse_json(_oku("evds_usdtry.json"), "TP.DK.USD.S.YTL")

    assert list(df.columns) == ["date", "value", "series_id"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["value"])
    assert (df["series_id"] == "TP.DK.USD.S.YTL").all()
    assert df["date"].is_monotonic_increasing
    assert df["value"].notna().all()

    # 7 satırdan ikisi (null ve '-') eksik: düşürülmüş olmalı; gün korunur
    assert len(df) == 5
    assert df["date"].iloc[0] == pd.Timestamp("2024-11-01")
    assert df["date"].iloc[-1] == pd.Timestamp("2024-11-11")
    # ondalık virgül (TR yerel biçimi) çözülmüş olmalı
    assert df.loc[df["date"] == pd.Timestamp("2024-11-06"), "value"].iloc[0] == pytest.approx(34.9517)
    assert df.loc[df["date"] == pd.Timestamp("2024-11-01"), "value"].iloc[0] == pytest.approx(34.2876)


def test_tr_sayi_karisik_bicimler():
    assert evds._tr_sayi("2,15", "X") == pytest.approx(2.15)
    assert evds._tr_sayi("1.234,56", "X") == pytest.approx(1234.56)
    assert evds._tr_sayi("10.5", "X") == pytest.approx(10.5)
    assert evds._tr_sayi(5, "X") == pytest.approx(5.0)
    assert pd.isna(evds._tr_sayi(None, "X"))
    assert pd.isna(evds._tr_sayi("", "X"))
    assert pd.isna(evds._tr_sayi("-", "X"))


@pytest.mark.parametrize(
    ("payload", "parca"),
    [
        ({"hata": "yanlış anahtar"}, "items"),
        ({"items": []}, "items"),
        ({"items": [{"Tarih": "01-11-2024", "TP_BASKA_SERI": "1,0"}]}, "TP_DK_USD_S_YTL"),
    ],
    ids=["items-yok", "items-bos", "seri-sutunu-yok"],
)
def test_sourceerror_beklenmedik_sema(payload, parca):
    with pytest.raises(SourceError, match=parca):
        evds.parse_json(payload, "TP.DK.USD.S.YTL")


def test_sourceerror_kismi_sutun_eksikligi():
    # şema sapması: bazı satırlarda seri sütunu hiç yok — sessiz düşürme yasak
    payload = {
        "items": [
            {"Tarih": "01-11-2024", "TP_DK_USD_S_YTL": "34,2876"},
            {"Tarih": "04-11-2024"},  # sütun yok: null değil, şema sapması
        ]
    }
    with pytest.raises(SourceError, match="sütunu eksik"):
        evds.parse_json(payload, "TP.DK.USD.S.YTL")


def test_acik_null_eksik_gozlemdir_sutun_eksikligi_degil():
    # anahtar var ama değeri null (tatil): eksik gözlem sayılıp düşürülür;
    # diğer satırlar korunur — şema sapmasından (yukarıdaki test) farklı davranış
    payload = {
        "items": [
            {"Tarih": "01-11-2024", "TP_DK_USD_S_YTL": None},
            {"Tarih": "04-11-2024", "TP_DK_USD_S_YTL": "34,4435"},
        ]
    }
    df = evds.parse_json(payload, "TP.DK.USD.S.YTL")

    assert len(df) == 1
    assert df["date"].iloc[0] == pd.Timestamp("2024-11-04")


@pytest.mark.parametrize(
    ("payload", "parca"),
    [
        ({"items": [{"Tarih": "2024/11/01", "TP_DK_USD_S_YTL": "34,2876"}]}, "anlaşılamadı"),
        ({"items": [{"Tarih": "01-11-2024", "TP_DK_USD_S_YTL": "onbes"}]}, "çözülemedi"),
        ({"items": [{"Tarih": "01-11-2024", "TP_DK_USD_S_YTL": None}]}, "gözlem"),
    ],
    ids=["tarih-bozuk", "junk-deger", "gozlem-kalmadi"],
)
def test_sourceerror_satir_seviyesi(payload, parca):
    # junk değer / bozuk tarih hatadır; hiç geçerli gözlem kalmazsa da hatadır
    with pytest.raises(SourceError, match=parca):
        evds.parse_json(payload, "TP.DK.USD.S.YTL")


def test_anahtarsiz_evdskeymissing():
    # plan T6: anahtar None → EvdsKeyMissing (CLI bu istisna üzerinden graceful skip eder)
    for anahtar in (None, "", "   "):
        with pytest.raises(evds.EvdsKeyMissing, match="EVDS"):
            evds.EvdsClient(anahtar)
    with pytest.raises(evds.EvdsKeyMissing, match="EVDS"):
        evds.fetch_all(None)


def test_seri_url_bicimi():
    url = evds.seri_url("TP.DK.USD.S.YTL", date(2025, 1, 1), date(2025, 1, 31))
    assert url == (
        "https://evds3.tcmb.gov.tr/igmevdsms-dis/series=TP.DK.USD.S.YTL"
        "&startDate=01-01-2025&endDate=31-01-2025&type=json"
    )


def test_sourceerror_gecersiz_seri_kodu_url_ye_girmez():
    with pytest.raises(SourceError):
        evds.seri_url("ornek/../sneak", date(2025, 1, 1), date(2025, 1, 31))


def test_get_anahtar_basligiyla_yonlendirmesiz_gider(monkeypatch):
    yakalanan = _ag_sahtele(monkeypatch)
    df = evds.EvdsClient("gizli-anahtar").get(
        "TP.DK.USD.S.YTL", date(2024, 11, 1), date(2024, 11, 30)
    )

    assert yakalanan["headers"]["key"] == "gizli-anahtar"
    assert yakalanan["headers"]["Accept"] == "application/json"
    assert yakalanan["allow_redirects"] is False
    assert yakalanan["host"] == "evds3.tcmb.gov.tr"
    assert len(df) == 5  # mutlu yol: fixture parse'a kadar akar


@pytest.mark.parametrize(
    ("yanit", "parca"),
    [
        (_SahteYanit(status_code=401, text="Invalid API Key"), "anahtar"),
        (_SahteYanit(status_code=302), "yönlendirildi"),  # eski evds2 yolu: takip edilmez
        (_SahteYanit(status_code=500), "500"),
        (_SahteYanit(status_code=200, text="<html>hata</html>"), "JSON"),
    ],
    ids=["401-anahtar", "302-yonlendirme", "500-bilinmeyen", "json-degil"],
)
def test_get_hata_yanitlari_sourceerror(monkeypatch, yanit, parca):
    _ag_sahtele(monkeypatch, [yanit])
    with pytest.raises(SourceError, match=parca):
        evds.EvdsClient("anahtar").get("TP.DK.USD.S.YTL", date(2024, 11, 1), date(2024, 11, 30))


def test_get_ag_hatasi_sourceerror(monkeypatch):
    _ag_sahtele(monkeypatch)

    def _patlat(url, **_):
        raise evds.requests.ConnectionError("bağlantı yok")

    monkeypatch.setattr(evds.requests, "get", _patlat)
    with pytest.raises(SourceError, match="başarısız"):
        evds.EvdsClient("anahtar").get("TP.DK.USD.S.YTL", date(2024, 11, 1), date(2024, 11, 30))


# dilim birleştirme (T11): örtüşen dilim yanıtlarında kopya ay
# eşit-değerli örtüşme = meşru örtüşme, sessiz dedup; farklı-değerli = SourceError


def test_parse_kopya_ay_esit_deger_dedup():
    payload = {
        "items": [
            {"Tarih": "2026-1", "TP_TUKFIY2025_GENEL": "115.73"},
            {"Tarih": "2026-2", "TP_TUKFIY2025_GENEL": "119.16"},
            {"Tarih": "2026-2", "TP_TUKFIY2025_GENEL": "119.16"},  # birebir eşit kopya
        ]
    }
    df = evds.parse_json(payload, "TP.TUKFIY2025.GENEL")

    assert len(df) == 2  # örtüşen ay tek satıra düştü
    assert df["date"].is_monotonic_increasing
    assert df.loc[df["date"] == pd.Timestamp("2026-02-01"), "value"].iloc[0] == pytest.approx(
        119.16
    )


def test_parse_kopya_ay_farkli_deger_sourceerror():
    payload = {
        "items": [
            {"Tarih": "2026-1", "TP_TUKFIY2025_GENEL": "115.73"},
            {"Tarih": "2026-1", "TP_TUKFIY2025_GENEL": "115.74"},  # aynı ay, farklı değer
        ]
    }
    with pytest.raises(SourceError, match="farklı değerli"):
        evds.parse_json(payload, "TP.TUKFIY2025.GENEL")


def test_get_ortusan_dilim_esit_deger_tek_satir(monkeypatch):
    # dilim yanıtları sınır gününde örtüşebilir: eşit değerli örtüşen gün tek satır
    _ag_sahtele(
        monkeypatch,
        [
            _SahteYanit(
                payload={
                    "items": [
                        {"Tarih": "01-01-2010", "TP_DK_USD_S_YTL": "1,0"},
                        {"Tarih": "18-06-2012", "TP_DK_USD_S_YTL": "1,5"},
                    ]
                }
            ),
            _SahteYanit(
                payload={
                    "items": [
                        {"Tarih": "18-06-2012", "TP_DK_USD_S_YTL": "1,5"},  # örtüşen dilim sınırı
                        {"Tarih": "19-06-2012", "TP_DK_USD_S_YTL": "1,6"},
                    ]
                }
            ),
        ],
    )
    df = evds.EvdsClient("anahtar").get("TP.DK.USD.S.YTL", date(2010, 1, 1), date(2012, 6, 19))

    assert len(df) == 3
    assert (df["date"] == pd.Timestamp("2012-06-18")).sum() == 1


def test_get_kopya_gun_farkli_deger_sourceerror(monkeypatch):
    _ag_sahtele(
        monkeypatch,
        [
            _SahteYanit(
                payload={"items": [{"Tarih": "01-01-2010", "TP_DK_USD_S_YTL": "1,0"}]}
            ),
            _SahteYanit(
                payload={
                    "items": [
                        {"Tarih": "01-01-2010", "TP_DK_USD_S_YTL": "2,0"},  # farklı değer
                    ]
                }
            ),
        ],
    )
    with pytest.raises(SourceError, match="farklı değerli"):
        evds.EvdsClient("anahtar").get("TP.DK.USD.S.YTL", date(2010, 1, 1), date(2012, 6, 19))


# canlı


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("EVDS_API_KEY"), reason="EVDS_API_KEY yok")
def test_live_usdtry():
    client = evds.EvdsClient(os.environ["EVDS_API_KEY"])
    df = client.get("TP.DK.USD.S.YTL", date(2025, 10, 1), date.today())
    assert df["date"].max() > pd.Timestamp("2025-06-01")
