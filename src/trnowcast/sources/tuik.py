"""TÜİK TÜFE çekicisi — yedek boru (aylık % değişim + genel endeks).

T9'dan beri ana boru EVDS'tir (bkz. evds.py); TÜİK yedeği karışım olmasın diye
AYRI seri adlarına yazar: turkiye_tufe_aylik_yuzde_tuik ve turkiye_tufe_endeks_tuik
(denetçi bulgusu, 2026-11-05: aynı adlara yazınca save_series registry girdisini
ezer, satır bazlı kaynak izi yanlış beyan olur — dürüstlük sözleşmesi md. 2).
İki seri: aylık % değişim (HESAPLANMAZ, kaynaktan gelir) ve genel endeks.
Ayrıştırma kuralları ve türetme (aylık yoksa veya tek tek boş aylar varsa
endeksten tamamlanır) tuik_parse.py içinde belgelenir.

Canlı kaynak (SDMX): TÜİK Veri Portalı dataflow TR,DF_TUFE_SDMX_TT10,1.0
("Tüketici fiyat endeksi ve değişim oranları"; kimlik veriportali.tuik.gov.tr
databrowser adresinden 2026-11-05'te doğrulandı):

    https://nsiws.tuik.gov.tr/rest/data/TR,DF_TUFE_SDMX_TT10,1.0/all?format=JSON&dimensionAtObservation=TIME_PERIOD

Uç nokta sözdizimi TÜİK'in resmî SDMX web servis dokümantasyonundandır
(veriportali.tuik.gov.tr/tr/sdmx-web-service-documentation, erişim 2026-11-05).
ERİŞİM DURUMU (dürüstlük notu): bu geliştirme ortamından TÜİK sunucularına
bağlantı resetlendiği için canlı indirme DOĞRULANAMADI; resmî dokümantasyon
tüm SDMX isteklerinde Bearer token (SMS doğrulamalı API anahtarı) istiyor —
401/403 yanıtında SourceError net mesaj verir, sessiz anahtarsız başarı yok.
Canlı doğrulama `live` işaretli teste aittir; canlı yol doğrulanana kadar
registry url'i "manuel:" notuyla yazılır.

Manuel yol (öncelikli): data/raw/tuik_tufe.xlsx varsa ağ hiç kullanılmaz.
Dosya, kullanıcının kendi tarayıcısından indirdiği TÜİK "Tüketici Fiyat
Endeksi ve Değişim Oranları" istatistiksel tablosudur (TÜİK otomasyona kapalı,
normal tarayıcıya açıktır). df.series_id kaynak ölçü kimlikleridir
("endeks", "aylik_yuzde"); fetch_all bunları meta.name'e çevirip T2 deposuna
yazar. Yayın gecikmesi ≈ 3 gün (plan T5).

Güvenlik: indirme öncesi URL denetlenir — yalnız https ve izin listesindeki
ana makine; localhost/loopback/özel/rezerve IP'ler (çözümlenen DNS IP'leri
dahil) reddedilir.
"""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests

from trnowcast import store
from trnowcast.sources import SourceError
from trnowcast.sources.tuik_parse import parse_jsonstat
from trnowcast.sources.tuik_tablo import parse_xlsx
from trnowcast.store import SeriesMeta, save_series

SERIES: dict[str, str] = {
    "turkiye_tufe_aylik_yuzde_tuik": "aylik_yuzde",
    "turkiye_tufe_endeks_tuik": "endeks",
}

SDMX_URL = (
    "https://nsiws.tuik.gov.tr/rest/data/"
    "TR,DF_TUFE_SDMX_TT10,1.0/all"
    "?format=JSON&dimensionAtObservation=TIME_PERIOD"
)
_SDMX_HOST = "nsiws.tuik.gov.tr"
_USER_AGENT = "trnowcast/0.1 (data pipeline; accessed 2026-11-05)"
_TIMEOUT_S = 30

MANUEL_DOSYA = "tuik_tufe.xlsx"
_PUBLICATION_LAG_DAYS = 3
_UNITS = {"endeks": "endeks (2025=100)", "aylik_yuzde": "yüzde (%)"}
# Değer aralığı uyarı eşikleri (ölçü bazlı, alt/üst) — serinin kendi üstverisi;
# quality kontrolü eşiği registry/meta'dan okur, burada olmayana uygulanmaz.
_UYARI_ARALIKLARI = {"aylik_yuzde": (-2.0, 20.0)}  # plan T7
_LICENSE_NOTE = (
    "TÜİK TÜFE verisi; TÜİK yasal uyarısına göre kaynak gösterilerek kullanım"
)


def _validate_url(url: str) -> None:
    """Yalnız https + izin listesindeki genel ana makineye izin verir."""
    parca = urlsplit(url)
    if parca.scheme != "https" or parca.hostname != _SDMX_HOST:
        raise SourceError(f"İzin verilmeyen TÜİK veri adresi: {url!r}")
    try:
        ip = ipaddress.ip_address(parca.hostname)
    except ValueError:
        return  # alan adı: DNS denetimi _cek'te istekten hemen önce yapılır
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise SourceError(f"Özel/rezerve adrese izin verilmez: {url!r}")


def _cek() -> dict:
    """SDMX JSONstat yanıtını güvenli çeker; şema dışı durumda SourceError."""
    _validate_url(SDMX_URL)
    try:
        kayitlar = socket.getaddrinfo(_SDMX_HOST, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as hata:
        raise SourceError(f"TÜİK adresi çözülemedi ({_SDMX_HOST}): {hata}") from hata
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
            SDMX_URL,
            timeout=_TIMEOUT_S,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=False,
        )
    except requests.RequestException as hata:
        raise SourceError(f"TÜİK SDMX isteği başarısız ({SDMX_URL}): {hata}") from hata
    if yanit.status_code in (401, 403):
        raise SourceError(
            "TÜİK SDMX Bearer token istiyor (SMS doğrulamalı API anahtarı gerekli) "
            f"[HTTP {yanit.status_code}]: data/raw/{MANUEL_DOSYA} manuel yolunu kullanın"
        )
    if yanit.status_code != 200:
        raise SourceError(f"TÜİK SDMX beklenmedik durum kodu {yanit.status_code}: {SDMX_URL}")
    try:
        return yanit.json()
    except ValueError as hata:
        raise SourceError(f"TÜİK SDMX yanıtı JSON çözülemedi: {hata}") from hata


def _manuel_yol() -> Path:
    return store.DATA_ROOT / "raw" / MANUEL_DOSYA


def _kaynak_oku() -> tuple[pd.DataFrame, str]:
    """Önce manuel xlsx, yoksa SDMX; (veri, kaynak url'i) döndürür."""
    manuel = _manuel_yol()
    if manuel.exists():
        return (
            parse_xlsx(manuel.read_bytes()),
            f"manuel: {MANUEL_DOSYA} (doğrulanmamış kaynak)",
        )
    return parse_jsonstat(_cek()), SDMX_URL


def fetch() -> pd.DataFrame:
    """Her iki TÜFE serisini (endeks + aylık %) long format döndürür."""
    return _kaynak_oku()[0]


def fetch_all() -> list[Path]:
    """İki seriyi çekip T2 deposuna yazar; parquet yollarını döndürür."""
    df, url = _kaynak_oku()
    yollar: list[Path] = []
    for seri_adi, olcu in SERIES.items():
        alt = df[df["series_id"] == olcu].reset_index(drop=True)
        if alt.empty:
            raise SourceError(
                f"TÜİK: '{seri_adi}' için kullanılabilir gözlem yok — sessiz boş "
                "parquet yazılmaz"
            )
        meta = SeriesMeta(
            name=seri_adi,
            source="TÜİK",
            url=url,
            frequency="aylık",
            units=_UNITS[olcu],
            publication_lag_days=_PUBLICATION_LAG_DAYS,
            license_note=_LICENSE_NOTE,
            warn_range=_UYARI_ARALIKLARI.get(olcu),
        )
        yollar.append(save_series(meta, alt))
    return yollar
