"""TCMB EVDS çekicisi: USD/TRY günlük kur + TÜFE ana borusu (T9).

Aylık TÜFE ana hedef serileri (endeks + aylık % değişim) EVDS borusundan gelir;
TÜİK çekicisi (tuik.py) yedektir ve ayrı "_tuik" adlarına yazar (registry izi karışmasın).
EVDS ücretsiz kayıt + anahtar ister (https://evds3.tcmb.gov.tr); anahtar ``EVDS_API_KEY``
ile gelir, ``key`` HTTP başlığı olarak gönderilir (URL'e konmaz, loglara sızmasın).

Veri URL'i (erişim/teyit tarihi: 2026-11-05, canlı doğrulandı):
- https://evds3.tcmb.gov.tr/igmevdsms-dis/series=<KOD>&startDate=<GG-AA-YYYY>&endDate=<GG-AA-YYYY>&type=json
- eski evds2.tcmb.gov.tr/service/evds/ yolu kaldırıldı (302); taban evds3'tür, yönlendirme takip edilmez.
- yanıt: {"items": [{"Tarih", "<KOD'da nokta yerine _>", "UNIXTIME"}, ...]}; değerler metin
  olabilir, ondalık virgül içerebilir (Review Focus 4). Tarih: günlük "GG-AA-YYYY", aylık
  "YYYY-M" (canlı teyit); iki biçim de ayrıştırılır.
- YANIT SINIRI: API yanıt başına en fazla 1000 gözlem döndürür ve fazlasını BAŞTAN sessiz
  kırpar (canlı teyit: 2010'dan istekte totalCount=1000, ilk satır 2024-02-10). get pencereyi
  900 günlük dilimlere böler; sınırı dolduran yanıt SourceError'dır — sessiz kırpılma yasak.

Seriler — kodlar 2026-11-05'te canlı API + EVDS 3 katalog API'siyle doğrulandı (katalog:
/igmevdsms-dis/categories/withDatagroups ve /serieList/fe uç noktaları, SPA paketinden çıkarıldı):
- usd_try_gunluk -> TP.DK.USD.S.YTL (ABD Doları Döviz Satış Kuru, TL/1 USD)
- turkiye_tufe_endeks -> TP.TUKFIY2025.GENEL (TÜFE Genel Endeksi 2025=100, aylık, TÜİK;
  2025=100 rebaze geçmişiyle en az 2010-1'den bugüne akıyor — canlı teyit 2026-11-05:
  2024-1 = 62.327275, Ekim 2026 = 140.77; depo penceresi 2010-01..2026-10, 202 ay).
  Eski 2003=100 genel endeks TP.FG.J0 arşivlendi (2026-1'de bitti); TP.TG2.Y* ailesi
  TÜFE değil Tüketici Güven Endeksi'dir — 30+ aday kod canlı tarandı, güncel tek
  TÜFE grubu bie_tukfiy2025.
- turkiye_tufe_aylik_yuzde -> türetilmiş: bie_tukfiy2025'in 349 serisi tarandı, doğrudan
  "aylık % değişim" serisi yok; plan T5/T9 yedeği uygulanır (pct_change × 100).
Yayın gecikmesi: günlük kur 1 gün; TÜFE TÜİK açıklama penceresini izler ≈ 3 gün.
"""

from __future__ import annotations

import ipaddress
import math
import re
import socket
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from trnowcast.sources import SourceError

# seri adı -> (EVDS kodu, frekans, birim, yayın gecikmesi, aylık-% türetme bayrağı)
SERI_META: dict[str, tuple[str, str, str, int, bool]] = {
    "usd_try_gunluk": ("TP.DK.USD.S.YTL", "günlük", "TL (1 USD karşılığı)", 1, False),
    "turkiye_tufe_endeks": ("TP.TUKFIY2025.GENEL", "aylık", "Endeks (2025=100)", 3, False),
    "turkiye_tufe_aylik_yuzde": ("TP.TUKFIY2025.GENEL", "aylık", "% (aylık, türetilmiş)", 3, True),
}
SERIES: dict[str, str] = {ad: meta[0] for ad, meta in SERI_META.items()}

# Değer aralığı uyarı eşikleri (alt, üst) — serinin kendi üstverisi; quality
# kontrolü eşiği registry/meta'dan okur, burada olmayan seriye uygulanmaz.
UYARI_ARALIKLARI: dict[str, tuple[float, float]] = {
    # plan T7: TÜFE aylık % için uyarı aralığı [-2, 20]
    "turkiye_tufe_aylik_yuzde": (-2.0, 20.0),
}

# İzin listesi: yalnız bu https ana makinesinden veri çekilir.
_EVDS_HOST = "evds3.tcmb.gov.tr"
_SERVIS_YOLU = "/igmevdsms-dis/"
_ZAMAN_ASIMI = 30
# EVDS yanıt başına en fazla 1000 gözlem döndürür ve fazlasını baştan kırpar (canlı teyit);
# günlük seride takvim günü başına 1 satır döndüğünden 900 günlük dilim sınıra ulaşamaz.
_YANIT_SINIRI = 1000
_DILIM_GUN = 900
_FETCH_BASLANGICI = date(2010, 1, 1)  # USD/TRY 2010'dan; TÜFE serileri kendi başından döner


class EvdsKeyMissing(SourceError):
    """EVDS anahtarı tanımsız/boş: CLI'ın graceful skip'i bu istisna üzerinden çalışır."""


class EvdsClient:
    """EVDS JSON API istemcisi. Anahtar yoksa/boşsa kurucu EvdsKeyMissing fırlatır."""

    def __init__(self, api_key: str | None):
        if not api_key or not str(api_key).strip():
            raise EvdsKeyMissing("EVDS anahtarı yok — EVDS_API_KEY ortam değişkenini tanımlayın.")
        self._anahtar = str(api_key).strip()

    def get(self, series: str, start: date, end: date) -> pd.DataFrame:
        """Seriyi [start, end] aralığında dilimlere bölerek çeker; long format döndürür."""
        items: list[dict] = []
        imlec = start
        while imlec <= end:
            dilim_sonu = min(imlec + timedelta(days=_DILIM_GUN - 1), end)
            payload = _guvenli_cek(seri_url(series, imlec, dilim_sonu), self._anahtar)
            dilim = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(dilim, list) or len(dilim) >= _YANIT_SINIRI:
                raise SourceError(
                    f"EVDS 'items' yok ya da yanıt sınırı doldu — kırpılma şüphesi: {series}"
                )
            items.extend(dilim)
            imlec = dilim_sonu + timedelta(days=1)
        return parse_json({"items": items}, series)


def seri_url(series: str, start: date, end: date) -> str:
    """EVDS veri adresini kurar; seri kodu EVDS kodu biçimine uymuyorsa reddeder."""
    if not re.fullmatch(r"[A-Z0-9.]+", series):
        raise SourceError(f"Geçersiz EVDS seri kodu: {series!r}")
    return (
        f"https://{_EVDS_HOST}{_SERVIS_YOLU}series={series}"
        f"&startDate={start:%d-%m-%Y}&endDate={end:%d-%m-%Y}&type=json"
    )


def _guvenli_cek(url: str, api_key: str) -> dict:
    """İzin listeli https isteği + genel IP denetimi + JSON ayrıştırma (fred._cek düzeni)."""
    parça = urlparse(url)
    if parça.scheme != "https" or parça.hostname != _EVDS_HOST:
        raise SourceError(f"İzin verilmeyen veri adresi: {url!r}")

    try:
        kayitlar = socket.getaddrinfo(parça.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as hata:
        raise SourceError(f"Adres çözülemedi ({_EVDS_HOST}): {hata}") from hata
    for kayit in kayitlar:
        ip = ipaddress.ip_address(kayit[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise SourceError(f"Çözümlenen adres reddedildi (özel/loopback/reserved): {ip}")

    try:
        yanit = requests.get(
            url,
            headers={"key": api_key, "Accept": "application/json"},
            timeout=_ZAMAN_ASIMI,
            allow_redirects=False,
        )
    except requests.RequestException as hata:
        raise SourceError(f"EVDS isteği başarısız ({url}): {hata}") from hata

    if 300 <= yanit.status_code < 400:
        raise SourceError(
            f"EVDS isteği yönlendirildi (HTTP {yanit.status_code}) — taban {_EVDS_HOST} olmalı."
        )
    if yanit.status_code in (401, 403):
        raise SourceError(f"EVDS anahtarı geçersiz/yetkisiz (HTTP {yanit.status_code}): {url}")
    if yanit.status_code != 200:
        raise SourceError(f"EVDS beklenmedik durum kodu {yanit.status_code}: {url}")
    try:
        return yanit.json()
    except ValueError as hata:
        raise SourceError(f"EVDS yanıtı JSON değil: {yanit.text[:200]!r}") from hata


def _tr_sayi(ham, series: str) -> float:
    """Değeri float'a çevirir; ondalık virgül desteklenir; null/''/'-' → NaN."""
    if ham is None or str(ham).strip() in {"", "-"}:
        return math.nan
    metin = str(ham).strip()
    if "," in metin and "." in metin:
        metin = metin.replace(".", "").replace(",", ".")
    elif "," in metin:
        metin = metin.replace(",", ".")
    try:
        return float(metin)
    except ValueError as hata:
        raise SourceError(f"EVDS değeri çözülemedi ({series}): {ham!r}") from hata


def parse_json(payload, series: str) -> pd.DataFrame:
    """EVDS JSON yanıtını long format çerçevesine çevirir; tarih günlük "GG-AA-YYYY",
    aylık "YYYY-M" gelir; null/'-'/'', düşer; anlaşılmayan değer/tarih hatadır.
    Birleşik dilim yanıtlarından gelen birebir eşit kopya tarih tek satıra düşürülür
    (meşru dilim örtüşmesi); farklı değerli kopya SourceError'dır.
    """
    if not isinstance(payload, dict):
        raise SourceError(f"EVDS yanıtı JSON nesnesi değil ({series}).")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise SourceError(f"EVDS yanıtında 'items' yok/boş ({series}).")

    anahtar = series.replace(".", "_")

    tarihler: list[pd.Timestamp] = []
    degerler: list[float] = []
    for satir in items:
        if not isinstance(satir, dict):
            raise SourceError(f"EVDS 'items' satırı nesne değil ({series}): {satir!r}")
        if satir.get("Tarih") in (None, ""):
            raise SourceError(f"EVDS satırında 'Tarih' yok ({series}): {satir!r}")
        if anahtar not in satir:
            raise SourceError(f"EVDS seri sütunu eksik: {anahtar!r} ({series}) — {satir!r}")
        try:
            tarih = pd.Timestamp(datetime.strptime(str(satir["Tarih"]), "%d-%m-%Y"))
        except ValueError:
            try:
                tarih = pd.Timestamp(datetime.strptime(str(satir["Tarih"]), "%Y-%m"))
            except ValueError as hata:
                raise SourceError(f"Tarih anlaşılamadı ({series}): {satir['Tarih']!r}") from hata
        deger = _tr_sayi(satir[anahtar], series)
        if math.isnan(deger):
            continue  # eksik gözlem (tatil vb.): düşürülür
        tarihler.append(tarih)
        degerler.append(deger)

    if not tarihler:
        raise SourceError(f"EVDS serisi {series}: geçerli gözlem yok.")

    # Dilim birleştirme (T11): get birden çok dilim yanıtını birleştirir; yanıtlar sınır
    # gününde örtüşebilir. Aynı tarih birebir eşit değerde tekrar gelirse meşru örtüşmedir
    # ve tek satıra düşürülür; farklı değerde gelirse veri çelişkisidir — sessiz üzerine
    # yazma ya da çift sayım yasaktır.
    benzersiz: dict[pd.Timestamp, float] = {}
    for tarih, deger in zip(tarihler, degerler):
        onceki = benzersiz.get(tarih)
        if onceki is not None and onceki != deger:
            raise SourceError(f"kopya ay {tarih:%Y-%m} — dilimler farklı değerli ({series})")
        benzersiz[tarih] = deger

    return pd.DataFrame(
        {
            "date": pd.Series(list(benzersiz), dtype="datetime64[ns]"),
            "value": pd.Series(list(benzersiz.values()), dtype="float64"),
            "series_id": series,
        }
    )


def _aylik_yuzde_turet(endeks_df: pd.DataFrame) -> pd.DataFrame:
    """Aylık genel endeksten aylık % türetir (pct_change × 100); ilk ay düşer, sessiz NaN yok.

    pct_change pozisyonel hesaplar: parse_json null ayı düşürdüğünde (evds.py) veya dilim
    birleştirmede kopya sızdığında ardışıklık bozulur — eksik ay iki aylık değişimi aylık %
    diye etiketler. Bu yüzden türetmeden önce kopya ay ve ay sürekliliği denetlenir;
    bozuk ardışıklık SourceError'dır, sessiz yanlış % yasaktır.
    """
    if endeks_df.empty:
        raise SourceError("turkiye_tufe_aylik_yuzde: en az 2 aylık endeks gözlemi gerekli")
    df = endeks_df.sort_values("date").reset_index(drop=True)
    # ay sayacı: yıl*12+ay — ay-başı normalize edilmemiş günleri de aynı aya sayar
    ay_sayaci = df["date"].dt.year * 12 + df["date"].dt.month
    kopya = df.loc[ay_sayaci.duplicated(), "date"]
    if not kopya.empty:
        raise SourceError(
            f"turkiye_tufe_aylik_yuzde: kopya ay {kopya.iloc[0]:%Y-%m} — dilim sızıntısı şüphesi"
        )
    bosluklar = ay_sayaci.diff().iloc[1:] != 1
    if bosluklar.any():
        i = bosluklar[bosluklar].index[0]
        raise SourceError(
            f"turkiye_tufe_aylik_yuzde: {df['date'].iloc[i - 1]:%Y-%m} ile "
            f"{df['date'].iloc[i]:%Y-%m} arasında ay boşluğu — iki aylık değişim aylık % olmaz"
        )
    df["value"] = df["value"].pct_change() * 100.0
    sonuc = df.iloc[1:]
    if sonuc.empty:
        raise SourceError("turkiye_tufe_aylik_yuzde: en az 2 aylık endeks gözlemi gerekli")
    return sonuc


def fetch_all(api_key: str | None) -> list[Path]:
    """SERI_META'daki tüm serileri çekip T2 deposuna yazar; parquet yolları döner.

    api_key None/boşsa EvdsKeyMissing — kurucuda, ağ çağrısından önce. Türetilen
    seri ayrı çekilmez: kod başına tek pencere, tarih ay-başına normalize, % türetilir.
    """
    client = EvdsClient(api_key)
    from trnowcast.store import SeriesMeta, save_series

    bitis = date.today()
    yollar: list[Path] = []
    ham: dict[str, pd.DataFrame] = {}
    for seri_adi, (kod, frekans, birim, gecikme, turetilmis) in SERI_META.items():
        if kod not in ham:
            ham[kod] = client.get(kod, _FETCH_BASLANGICI, bitis)
        df = ham[kod].copy()
        if frekans == "aylık":
            df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
        if turetilmis:
            df = _aylik_yuzde_turet(df)
        df["series_id"] = seri_adi
        meta = SeriesMeta(
            name=seri_adi,
            source="TCMB EVDS",
            url=seri_url(kod, _FETCH_BASLANGICI, bitis),
            frequency=frekans,
            units=birim,
            publication_lag_days=gecikme,
            license_note="TCMB EVDS ücretsiz kayıt + anahtar (EVDS_API_KEY) gerektirir",
            warn_range=UYARI_ARALIKLARI.get(seri_adi),
        )
        yollar.append(save_series(meta, df))
    return yollar
