"""FAO Gıda Fiyat Endeksi (FPIS) çekicisi — aylık nominal toplam endeks.

Veri URL'i (resmî fao.org, aylık nominal CSV):
    https://www.fao.org/media/docs/worldfoodsituationlibraries/wfs-library/food_price_indices_data.csv
Erişim: 2026-11-05 — HTTP 200, 445 satır, en güncel ay 2026-09.
(Kaynak sayfa: https://www.fao.org/worldfoodsituation/foodpricesindex/en)

Dosya biçimi: ilk iki satır başlıktır ("FAO Food Price Index", taban "2014-2016=100"),
üçüncü satır sütun başlığı ("Date,Food Price Index,Meat,Dairy,Cereals,Oils,Sugar"),
sonrasında aylık satırlar ("1990-01,64.4,...") ve aralarda boş ayraç satırları vardır.
Bu modül yalnız toplam endeksi ("Food Price Index") alır; et/süt/tahıl/yağ/şeker
alt endeksleri kapsam dışıdır (T4: aylık FPIS toplam endeks, long format).

Yayın gecikmesi: FAO endeksi, veri ayını izleyen ayın ilk haftasında açıklanır;
plan T4 meta kaydını güvenli üst sınır olarak ≈30 gün sabitler ve meta testi
``publication_lag_days == 30``ı doğrular.

Güvenlik notu: indirme öncesi URL doğrulanır — yalnız http/https şemalarına izin
verilir; localhost/loopback/özel/rezerve adresler reddedilir.
"""

from __future__ import annotations

import csv
import ipaddress
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests

from trnowcast.sources import SourceError
from trnowcast.store import SeriesMeta, save_series

SERIES_NAME = "fao_gida_endeks"

DATA_URL = (
    "https://www.fao.org/media/docs/worldfoodsituationlibraries/"
    "wfs-library/food_price_indices_data.csv"
)

_USER_AGENT = "trnowcast/0.1 (data pipeline; accessed 2026-11-05)"
_TIMEOUT_S = 60
_DATE_FORMAT = "%Y-%m"
_TOTAL_COLUMN = "Food Price Index"

META = SeriesMeta(
    name=SERIES_NAME,
    source="FAO",
    url=DATA_URL,
    frequency="aylık",
    units="2014-2016=100",
    publication_lag_days=30,
    license_note=(
        "FAO gıda fiyat endeksi verisi (fao.org); kullanım FAO veri paylaşım "
        "koşullarına tabidir (erişim 2026-11-05)"
    ),
)


def _validate_url(url: str) -> None:
    """Yalnız http(s) ve genel adreslere izin verir; aksi halde SourceError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SourceError(f"güvensiz veya geçersiz URL: {url!r}")
    host = parts.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        lowered = host.lower()
        engelli = ("localhost", "local", "internal")
        if lowered in engelli or lowered.endswith((".localhost", ".local", ".internal")):
            raise SourceError(f"yerel adrese izin verilmez: {url!r}") from None
    else:
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SourceError(f"özel/rezerve adrese izin verilmez: {url!r}")


def parse_fpis(text: str) -> pd.DataFrame:
    """FPIS CSV metnini long-format DataFrame'e çevirir (yalnız toplam endeks).

    Beklenen şema: ilk alanı ``Date`` olan bir başlık satırı, ilk sütunda
    ``YYYY-MM`` tarih, ``Food Price Index`` sütununda toplam endeks. Değeri boş
    olan aylar düşürülür; şema bozuksa veya tarih/sayı çözülemezse SourceError
    fırlatılır (sessiz boş DataFrame yok).
    """
    rows = list(csv.reader(text.splitlines()))
    header_i = next(
        (i for i, r in enumerate(rows) if r and r[0].strip() == "Date"), None
    )
    if header_i is None:
        raise SourceError(
            "FPIS CSV'sinde 'Date' başlık satırı bulunamadı — FAO şeması "
            "değişmiş olabilir; güncel dosyayı elle kontrol edin"
        )
    header = [c.strip() for c in rows[header_i]]
    if _TOTAL_COLUMN not in header:
        raise SourceError(
            f"FPIS CSV'sinde '{_TOTAL_COLUMN}' sütunu yok — sütun adları: "
            f"{[c for c in header if c]}"
        )
    value_i = header.index(_TOTAL_COLUMN)

    kayitlar: list[tuple[datetime, float, str]] = []
    for satir_no, r in enumerate(rows[header_i + 1 :], start=header_i + 2):
        if not r or not r[0].strip():
            continue  # boş ayraç satırı
        if len(r) <= value_i:
            raise SourceError(
                f"FPIS satır {satir_no}: '{_TOTAL_COLUMN}' sütunu eksik — "
                f"beklenen şema bozulmuş olabilir: {r!r}"
            )
        raw_date, raw_value = r[0].strip(), r[value_i].strip()
        try:
            date = datetime.strptime(raw_date, _DATE_FORMAT)
        except ValueError:
            raise SourceError(
                f"FPIS satır {satir_no}: beklenmeyen tarih biçimi {raw_date!r} "
                f"(beklenen {_DATE_FORMAT})"
            ) from None
        if not raw_value:
            continue  # değeri boş ay düşürülür
        try:
            value = float(raw_value)
        except ValueError:
            raise SourceError(
                f"FPIS satır {satir_no}: sayıya çevrilemeyen değer {raw_value!r}"
            ) from None
        kayitlar.append((date, value, SERIES_NAME))

    if not kayitlar:
        raise SourceError("FPIS CSV'sinde geçerli veri satırı bulunamadı")

    df = pd.DataFrame(kayitlar, columns=["date", "value", "series_id"])
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype(float)
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def fetch() -> pd.DataFrame:
    """Aylık FPIS toplam endeksini fao.org'dan indirir; long format döndürür."""
    _validate_url(DATA_URL)
    try:
        response = requests.get(
            DATA_URL, timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceError(f"FAO FPIS indirilemedi ({DATA_URL}): {exc}") from exc
    try:
        text = response.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError(f"FAO FPIS yanıtı UTF-8 çözülemedi: {exc}") from exc
    return parse_fpis(text)


def fetch_all() -> list[Path]:
    """FPIS'i çekip depoya (parquet + registry) yazar; parquet yolunu döndürür."""
    return [save_series(META, fetch())]
