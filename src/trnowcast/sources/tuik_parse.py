"""TÜİK SDMX JSONstat ayrıştırıcısı ve paylaşılan yardımcılar.

Salt ayrıştırma (ağ/depo erişimi yok); tuik.py canlı kaynağı bağlar, TR-yerel
xlsx ayrıştırıcısı tuik_tablo.py'dedir. Çıktı long format: date (ay-başı),
value (float), series_id ("endeks" | "aylik_yuzde"). Şema tanınmazsa
SourceError fırlatılır; sessiz boş çerçeve döndürülmez. Aylık % kaynaktan
gelir; gelmeyen aylar (tamamı yoksa tüm seri) endeksten türetilir (t-1'e
göre yüzde değişim × 100; plan T5'in izni). Biçim kanıtı (değerler sentetik,
yalnız biçim): tests/fixtures/tuik_tufe_sdmx.json.
"""

from __future__ import annotations

import itertools
import re

import pandas as pd

from trnowcast.sources import SourceError

_TARIH_KODU = re.compile(r"^(\d{4})-(\d{2})$")
_TR_CEVRIM = str.maketrans("ığüşöçİĞÜŞÖÇ", "igusocigusoc")


def _tr_norm(metin: str) -> str:
    """Türkçe karakter duyarsız karşılaştırma anahtarı (Aylık -> aylik)."""
    return str(metin).translate(_TR_CEVRIM).casefold().strip()


def _endeks_etiketi_mi(n: str) -> bool:
    return "endeks" in n


def _aylik_etiketi_mi(n: str) -> bool:
    # FREQ'in salt 'Aylık' etiketi ölçü sanılmasın (değişim/% şartı); '12 aylık
    # ortalama değişim' ayrı bir ölçüdür, ana hedef 'aylık değişim'dir
    return (
        "aylik" in n
        and ("degisim" in n or "%" in n)
        and "endeks" not in n
        and "ortalama" not in n
    )


def _sayi(hucre) -> float | None:
    """TR-yerel hücreyi sayıya çevirir; boş/eksik işaretli hücre None döner."""
    if hucre is None or isinstance(hucre, bool):
        return None
    if isinstance(hucre, (int, float)):
        return float(hucre)
    metin = str(hucre).strip()
    if metin in {"", "..", "-"}:
        return None
    if "," in metin:  # TR biçimi: nokta binlik, virgül ondalık
        metin = metin.replace(".", "").replace(",", ".")
    try:
        return float(metin)
    except ValueError as hata:
        raise SourceError(f"TÜİK: sayıya çevrilemeyen hücre: {metin!r}") from hata


def _cerceve(gozlemler: list[tuple[pd.Timestamp, float]], seri_kodu: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series([t for t, _ in gozlemler], dtype="datetime64[ns]"),
            "value": pd.Series([v for _, v in gozlemler], dtype="float64"),
            "series_id": seri_kodu,
        }
    )


def _aylik_turet(endeks: pd.DataFrame) -> pd.DataFrame:
    """Endeksten aylık % değişim türetir (t-1 baz); ilk ay gözlemi üretilmez."""
    sirali = endeks.sort_values("date")
    degerler, tarihler = sirali["value"].tolist(), sirali["date"].tolist()
    gozlemler = [
        (tarihler[i], (degerler[i] / degerler[i - 1] - 1) * 100)
        for i in range(1, len(degerler))
    ]
    return _cerceve(gozlemler, "aylik_yuzde")


def _ikili_cerceve(endeks: pd.DataFrame, aylik: pd.DataFrame | None) -> pd.DataFrame:
    """İki seriyi birleştirir; sıra (series_id, date).

    Aylık %: kaynaktan gelen aylar aynen korunur; kaynakta olmayan aylar
    (ölçü tümüyle yoksa tüm seri, tek tek '..' boşluklu aylar ise yalnız o
    hücreler) endeksten türetilerek tamamlanır — en güncel ay sessiz kayba
    dönüşmez. Endeksin t-1'i olmadığı ilk ay türetilmez.
    """
    turetilmis = _aylik_turet(endeks)
    if aylik is None or aylik.empty:
        aylik = turetilmis
    else:
        eksik = turetilmis[~turetilmis["date"].isin(set(aylik["date"]))]
        aylik = pd.concat([aylik, eksik], ignore_index=True)
    df = pd.concat([endeks, aylik], ignore_index=True)
    return df.sort_values(["series_id", "date"], kind="stable").reset_index(drop=True)


def _tek_kod_sec(adaylar: list[tuple], tur: str) -> tuple | None:
    """'genel' içeren adayı tercih eder; hâlâ belirsizse SourceError fırlatır."""
    if not adaylar:
        return None
    genel = [a for a in adaylar if "genel" in a[1]]
    secilen = genel or adaylar
    if len(secilen) > 1:
        raise SourceError(
            f"TÜİK: birden çok {tur} ayırt edilemedi: {[a[1] for a in secilen]}"
        )
    return secilen[0]


def _olcu_adaylari(etiketler: dict[str, str], kural) -> list[tuple[str, str]]:
    """Kod->etiket haritasından kurala uyan (kod, norm-etiket) adaylarını seçer."""
    return [(k, n) for k, e in etiketler.items() if kural(n := _tr_norm(e))]


def _kategori_haritalari(boyutlar, boyut_sozluk):
    """Her boyut için (pozisyon->kod, kod->etiket) haritalarını çıkarır."""
    poz_kod: dict[str, dict[int, str]] = {}
    kod_etiket: dict[str, dict[str, str]] = {}
    for ad in boyutlar:
        kategori = boyut_sozluk.get(ad, {})
        kategori = kategori.get("category", {}) if isinstance(kategori, dict) else {}
        dizin = kategori.get("index", {}) if isinstance(kategori, dict) else None
        if isinstance(dizin, dict):
            poz_kod[ad] = {int(p): kod for kod, p in dizin.items()}
        elif isinstance(dizin, list):
            poz_kod[ad] = dict(enumerate(dizin))
        else:
            raise SourceError(f"TÜİK SDMX JSONstat '{ad}' kategorisi bozuk")
        etiketler = kategori.get("label", {}) if isinstance(kategori, dict) else {}
        kod_etiket[ad] = etiketler if isinstance(etiketler, dict) else {}
    return poz_kod, kod_etiket


def parse_jsonstat(payload: dict) -> pd.DataFrame:
    """TÜİK SDMX JSONstat dataset'ini long format çerçevesine çevirir.

    Genel JSONstat okuma: 'id' sırası + 'size' boyutlarıyla 'value' düz dizisi
    taranır; zaman boyutu ('time' ya da YYYY-AA kodlu kategoriler) ve ölçü
    boyutu (etiketinde endeks / aylık değişim geçen boyut) tanınır. 'genel'
    etiketli kod tercih edilir; birden çok aday kalırsa şema belirsiz sayılır.
    Eksik (null) gözlemler düşürülür; şema tanınmazsa SourceError fırlatılır.
    """
    if not isinstance(payload, dict) or payload.get("class") != "dataset":
        raise SourceError("TÜİK SDMX yanıtı JSONstat dataset değil")
    boyutlar, boylar = payload.get("id"), payload.get("size")
    degerler, boyut_sozluk = payload.get("value"), payload.get("dimension")
    if not (
        isinstance(boyutlar, list)
        and isinstance(boylar, list)
        and isinstance(degerler, list)
        and isinstance(boyut_sozluk, dict)
    ) or not boyutlar or len(boyutlar) != len(boylar):
        raise SourceError("TÜİK SDMX JSONstat şeması eksik/bozuk: id/size/value/dimension")
    if not degerler or any(not isinstance(b, int) or b < 0 for b in boylar):
        raise SourceError("TÜİK SDMX JSONstat 'value' boş veya boyutlar bozuk")

    poz_kod, kod_etiket = _kategori_haritalari(boyutlar, boyut_sozluk)

    zaman_adi = next((d for d in boyutlar if d == "time"), None)
    if zaman_adi is None:
        zaman_adi = next(
            (
                d
                for d in boyutlar
                if poz_kod[d] and all(_TARIH_KODU.match(k) for k in poz_kod[d].values())
            ),
            None,
        )
    if zaman_adi is None:
        raise SourceError("TÜİK SDMX JSONstat'ta zaman boyutu bulunamadı")

    olcu_adi = next(
        (
            d
            for d in boyutlar
            if d != zaman_adi
            and any(
                _endeks_etiketi_mi(n) or _aylik_etiketi_mi(n)
                for n in map(_tr_norm, kod_etiket[d].values())
            )
        ),
        None,
    )
    if olcu_adi is None:
        raise SourceError(
            "TÜİK SDMX JSONstat'ta endeks/aylık-değişim ölçü boyutu tanınamadı "
            "— TÜİK şeması değişmiş olabilir"
        )

    endesk_aday = _tek_kod_sec(
        _olcu_adaylari(kod_etiket[olcu_adi], _endeks_etiketi_mi), "endeks kodu"
    )
    if endesk_aday is None:
        raise SourceError("TÜİK SDMX yanıtında genel endeks ölçüsü yok")
    endeks_kodu = endesk_aday[0]
    aylik_aday = _tek_kod_sec(
        _olcu_adaylari(kod_etiket[olcu_adi], _aylik_etiketi_mi), "aylık değişim kodu"
    )
    aylik_kodu = aylik_aday[0] if aylik_aday else None

    adimlar, carpan = [], 1
    for boy in reversed(boylar):
        adimlar.append(carpan)
        carpan *= boy
    adimlar.reverse()

    endeks_gozlem: dict[pd.Timestamp, float] = {}
    aylik_gozlem: dict[pd.Timestamp, float] = {}
    for konum in itertools.product(*(range(b) for b in boylar)):
        ofset = sum(p * a for p, a in zip(konum, adimlar))
        if ofset >= len(degerler) or degerler[ofset] is None:
            continue
        kodlar = {ad: poz_kod[ad].get(p) for ad, p in zip(boyutlar, konum)}
        eslesme = _TARIH_KODU.match(str(kodlar[zaman_adi]))
        if eslesme is None:
            continue
        tarih = pd.Timestamp(int(eslesme.group(1)), int(eslesme.group(2)), 1)
        olcu_kodu = kodlar.get(olcu_adi)
        if olcu_kodu == endeks_kodu:
            endeks_gozlem.setdefault(tarih, float(degerler[ofset]))
        elif aylik_kodu is not None and olcu_kodu == aylik_kodu:
            aylik_gozlem.setdefault(tarih, float(degerler[ofset]))

    if not endeks_gozlem:
        raise SourceError("TÜİK SDMX yanıtında kullanılabilir endeks gözlemi yok")
    return _ikili_cerceve(
        _cerceve(sorted(endeks_gozlem.items()), "endeks"),
        _cerceve(sorted(aylik_gozlem.items()), "aylik_yuzde") if aylik_gozlem else None,
    )
