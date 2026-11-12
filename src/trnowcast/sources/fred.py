"""FRED çekicileri: Türkiye TÜFE endeksi yedeği ve Brent petrolü.

Sorumluluk: TÜİK TÜFE'sinin yedeği (tek kaynağa bağımlılık yasağı, spec
"anti-hedefler" maddesi) ve günlük brent sürücüsü. Her iki seri de FRED'in
anahtarsız CSV servisinden çekilir.

Veri URL'leri (erişim tarihi: 2026-11-05, canlı doğrulandı):
- turkiye_tufe_endeks_fred: https://fred.stlouisfed.org/graph/fredgraph.csv?id=TURCPIALLMINMEI
  (OECD, "Consumer Price Index: All Items: Monthly for Turkey",
   Index 2015=100, Not Seasonally Adjusted; FRED son güncelleme 15 Mayıs 2025)
- brent_gunluk: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU
  (EIA, "Crude Oil Prices: Brent - Europe", USD/varil)

CSV biçimi (2026-11-05 itibarıyla canlıdan görülen): başlık satırı
`observation_date,<SERIES_ID>`; eksik gözlemler "." (bazı serilerde) veya boş
alan (brent'te görüldü) olarak gelir — ikisi de NaN sayılıp düşürülür.

Yayın gecikmeleri: TURCPIALLMINMEI ≈ 45 gün (OECD derlemesi), DCOILBRENTEU ≈ 2 gün.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from trnowcast.sources import SourceError
from trnowcast.store import SeriesMeta, save_series

SERIES: dict[str, str] = {
    "turkiye_tufe_endeks_fred": "TURCPIALLMINMEI",
    "brent_gunluk": "DCOILBRENTEU",
}

# İzin listesi: yalnız bu https ana makinesinden veri çekilir. localhost, loopback,
# özel ağ ve reserved adresler bu listeyle ve aşağıdaki IP denetimiyle reddedilir.
_FRED_HOST = "fred.stlouisfed.org"

# seri kodu → yayın gecikmesi (gün); plan T3: TURCPIALLMINMEI ≈ 45, DCOILBRENTEU ≈ 2
_PUBLICATION_LAG_DAYS = {"TURCPIALLMINMEI": 45, "DCOILBRENTEU": 2}

# seri adı → SeriesMeta'nın kaynak-bağımsız alanları
_META_BILGISI = {
    "turkiye_tufe_endeks_fred": {
        "frequency": "aylık",
        "units": "endeks (2015=100, mevsimsel düzeltilmemiş)",
        "license_note": "OECD verisi, FRED üzerinden; FRED atıf koşullarıyla serbest kullanım",
    },
    "brent_gunluk": {
        "frequency": "günlük",
        "units": "USD/varil",
        "license_note": "EIA verisi, FRED üzerinden; FRED atıf koşullarıyla serbest kullanım",
    },
}


def _seri_url(series_id: str) -> str:
    """fredgraph.csv adresini kurar; seri kodu FRED kodu biçimine uymuyorsa reddeder."""
    if not re.fullmatch(r"[A-Z0-9]+", series_id):
        raise SourceError(f"Geçersiz FRED seri kodu: {series_id!r}")
    return f"https://{_FRED_HOST}/graph/fredgraph.csv?id={series_id}"


def _cek(series_id: str) -> str:
    """FRED CSV'sini güvenli çeker. Sıra: kod biçimi → https + ana makine izin listesi →
    DNS çözümle → çözümlenen her IP genel olmalı (localhost/loopback/özel/保留 reddi) →
    yönlendirme kapalı istek. DNS rebinding'e karşı çözümlenen IP denetimi istekten
    hemen önce yapılır."""
    if not re.fullmatch(r"[A-Z0-9]+", series_id):
        raise SourceError(f"Geçersiz FRED seri kodu: {series_id!r}")

    url = f"https://{_FRED_HOST}/graph/fredgraph.csv?id={series_id}"
    parça = urlparse(url)
    if parça.scheme != "https" or parça.hostname != _FRED_HOST:
        raise SourceError(f"İzin verilmeyen veri adresi: {url!r}")

    try:
        kayitlar = socket.getaddrinfo(parça.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as hata:
        raise SourceError(f"Adres çözülemedi ({_FRED_HOST}): {hata}") from hata
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
        yanit = requests.get(url, timeout=30, allow_redirects=False)
    except requests.RequestException as hata:
        raise SourceError(f"FRED isteği başarısız ({url}): {hata}") from hata
    if yanit.status_code != 200:
        raise SourceError(f"FRED beklenmedik durum kodu {yanit.status_code}: {url}")
    return yanit.text


def parse_csv(govde: str, series_id: str) -> pd.DataFrame:
    """FRED CSV gövdesini long format çerçevesine çevirir.

    Sütunlar konumsal okunur (tarih, değer); başlık adları sürüme göre değişebildiği
    için yalnız bilinen başlıklar kabul edilir. "." ve boş değerler düşürülür.
    """
    satirlar = [s for s in (satir.strip() for satir in govde.splitlines()) if s]
    if len(satirlar) < 2:
        raise SourceError(f"FRED yanıtı boş veya başlıksız ({series_id}).")

    baslik = satirlar[0].split(",")
    if len(baslik) != 2 or baslik[0] not in {"observation_date", "DATE"}:
        raise SourceError(f"Beklenmedik FRED başlığı ({series_id}): {satirlar[0]!r}")

    tarihler: list[pd.Timestamp] = []
    degerler: list[float] = []
    for satir in satirlar[1:]:
        parcalar = satir.split(",")
        if len(parcalar) != 2:
            raise SourceError(f"Beklenmedik satır biçimi ({series_id}): {satir!r}")
        tarih_metni, deger_metni = parcalar[0], parcalar[1].strip()
        try:
            tarih = pd.Timestamp(tarih_metni)
        except ValueError as hata:
            raise SourceError(f"Tarih çözülemedi ({series_id}): {tarih_metni!r}") from hata
        if deger_metni in {".", ""}:
            continue  # eksik gözlem: NaN sayılıp düşürülür
        try:
            deger = float(deger_metni)
        except ValueError as hata:
            raise SourceError(f"Değer çözülemedi ({series_id}): {deger_metni!r}") from hata
        tarihler.append(tarih)
        degerler.append(deger)

    if not tarihler:
        # Sessiz boş çerçeve döndürmek fetch_all'u boş parquet yazdırıp registry'yi
        # tazeletirdi; seri var gibi görünürdü (plan genel kısıtı: boş dönüş yok).
        raise SourceError(
            f"FRED yanıtında kullanılabilir gözlem yok ({series_id}): "
            "tüm satırlar eksik değerli."
        )

    return pd.DataFrame(
        {
            "date": pd.Series(tarihler, dtype="datetime64[ns]"),
            "value": pd.Series(degerler, dtype="float64"),
            "series_id": series_id,
        }
    )


def fetch_series(series_id: str) -> pd.DataFrame:
    """FRED'den tek seri çeker; long format (date, value, series_id) döndürür."""
    return parse_csv(_cek(series_id), series_id)


def fetch_all() -> list[Path]:
    """SERIES'teki tüm serileri çekip T2 deposuna yazar; parquet yollarını döndürür."""
    yollar: list[Path] = []
    for seri_adi, fred_id in SERIES.items():
        df = fetch_series(fred_id)
        bilgi = _META_BILGISI[seri_adi]
        meta = SeriesMeta(
            name=seri_adi,
            source="FRED",
            url=_seri_url(fred_id),
            frequency=bilgi["frequency"],
            units=bilgi["units"],
            publication_lag_days=_PUBLICATION_LAG_DAYS[fred_id],
            license_note=bilgi["license_note"],
        )
        yollar.append(save_series(meta, df))
    return yollar
