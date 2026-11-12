"""TÜİK istatistiksel tablo (TR-yerel xlsx) ayrıştırıcısı.

Manuel yolun biçimi: "YYYY-Ay" dönem başlıkları (Oca…Ara kısaltmaları),
TR-yerel sayılar (nokta binlik, virgül ondalık) ve etiketinde "endeks" /
"aylık değişim" geçen satırlar. Salt ayrıştırma (ağ/depo erişimi yok);
paylaşılan yardımcılar tuik_parse.py'dedir. Biçim kanıtı:
tests/fixtures/tuik_tufe.xlsx (değerler sentetik, yalnız biçim).
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

import pandas as pd

from trnowcast.sources import SourceError
from trnowcast.sources.tuik_parse import (
    _aylik_etiketi_mi,
    _cerceve,
    _endeks_etiketi_mi,
    _ikili_cerceve,
    _sayi,
    _tek_kod_sec,
    _tr_norm,
)

_AY_ADLARI = {
    "oca": 1, "şub": 2, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6,
    "tem": 7, "ağu": 8, "agu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
}
_DONEM_KALIBI = re.compile(r"^(\d{4})-([A-Za-zçğıöşüÇĞİÖŞÜ]{3})$")


def _donem_hucresi(hucre) -> tuple[int, int] | None:
    """'2025-Oca' biçimli hücreyi (yıl, ay) ikilisine çevirir; değilse None."""
    eslesme = _DONEM_KALIBI.match(str(hucre).strip()) if hucre is not None else None
    if eslesme is None:
        return None
    ay = _AY_ADLARI.get(_tr_norm(eslesme.group(2)))
    return (int(eslesme.group(1)), ay) if ay else None


def parse_xlsx(veri: bytes) -> pd.DataFrame:
    """TÜİK istatistiksel tablo xlsx'ini (TR-yerel biçim) long formata çevirir.

    Dönem başlıkları ('2025-Oca'…, en az üç sütun) başlık satırını belirler;
    etiketinde 'endeks' geçen satır endeks, 'aylık değişim' geçen satır aylık
    ölçü sayılır ('genel' içeren satır tercih edilir; değer taşımayan satırlar
    aday değildir). Aylık satır yoksa endeksten türetilir; endeks satırı yoksa
    sütun kaybı sayılır ve SourceError fırlatılır.
    """
    try:
        tablo = pd.read_excel(BytesIO(veri), header=None, engine="openpyxl")
    except (ValueError, zipfile.BadZipFile) as hata:
        raise SourceError(f"TÜİK xlsx okunamadı: {hata}") from hata
    hucreler = tablo.values.tolist()

    baslik_i, donemler, etiket_j = None, None, 0
    for i, satir in enumerate(hucreler):
        eslesen = {j: c for j, h in enumerate(satir) if (c := _donem_hucresi(h))}
        if len(eslesen) >= 3:
            baslik_i, donemler = i, eslesen
            etiket_j = next(
                (j for j, h in enumerate(satir) if h is not None and j not in eslesen), 0
            )
            break
    if baslik_i is None:
        raise SourceError(
            "TÜİK tablosunda dönem başlık satırı bulunamadı (YYYY-Ay sütunları) "
            "— sütun kaybı veya biçim değişikliği"
        )

    endeks_aday: list[tuple[str, list[tuple[pd.Timestamp, float]]]] = []
    aylik_aday: list[tuple[str, list[tuple[pd.Timestamp, float]]]] = []
    for satir in hucreler[baslik_i + 1 :]:
        etiket = satir[etiket_j] if etiket_j < len(satir) else None
        if etiket is None:
            continue
        n = _tr_norm(str(etiket))
        gozlemler = [
            (pd.Timestamp(y, a, 1), v)
            for j, (y, a) in donemler.items()
            if j < len(satir) and (v := _sayi(satir[j])) is not None
        ]
        if not gozlemler:
            continue  # değer taşımayan satırlar (başlık/dipnot) aday değildir
        if _endeks_etiketi_mi(n):
            endeks_aday.append((n, gozlemler))
        elif _aylik_etiketi_mi(n):
            aylik_aday.append((n, gozlemler))

    endeks_secim = _tek_kod_sec(endeks_aday, "endeks satırı")
    if endeks_secim is None:
        raise SourceError(
            "TÜİK tablosunda genel endeks satırı bulunamadı — sütun kaybı "
            f"(aday satırlar: {[a[0] for a in endeks_aday]})"
        )
    aylik_secim = _tek_kod_sec(aylik_aday, "aylık değişim satırı")
    return _ikili_cerceve(
        _cerceve(endeks_secim[1], "endeks"),
        _cerceve(aylik_secim[1], "aylik_yuzde") if aylik_secim else None,
    )
