"""TÜİK TR-yerel istatistiksel tablo (xlsx) ayrıştırıcı testleri — offline.

Fixture "değerler sentetik, yalnız biçim kanıtı" ilkesiyle kuruludur:
tuik_tufe.xlsx TÜİK istatistiksel tablo düzenini (Oca ay adları, virgül
ondalık, nokta binlik) temsil eder; gerçek TÜİK verisi değildir.
"""

from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from trnowcast.sources import SourceError, tuik

FIXTURE_DIR = Path(__file__).parent / "fixtures"

ENDEKS_FIXTURE = [98.1, 99.24, 100.9, 101.02, 102.55, 103.77]
AYLIK_FIXTURE = [1.15, 1.16, 1.67, 0.12, 1.51, 1.19]


def _xlsx_oku(dosya: str) -> bytes:
    return (FIXTURE_DIR / dosya).read_bytes()


def _wb_bytes(wb) -> bytes:
    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def _seri(df: pd.DataFrame, kod: str) -> pd.DataFrame:
    return df[df["series_id"] == kod].sort_values("date")


def test_xlsx_fixture_tr_yerel_bicim_long_format():
    df = tuik.parse_xlsx(_xlsx_oku("tuik_tufe.xlsx"))

    assert list(df.columns) == ["date", "value", "series_id"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["value"])
    assert set(df["series_id"]) == {"endeks", "aylik_yuzde"}
    assert len(df) == 12
    assert (df["date"].dt.day == 1).all()  # aylık seri ay-başı tarihlerde
    for seri in ("endeks", "aylik_yuzde"):
        assert _seri(df, seri)["date"].is_monotonic_increasing

    endeks = _seri(df, "endeks")
    # virgül ondalık doğru çözüldü: "98,10" -> 98.10
    assert endeks["value"].tolist() == ENDEKS_FIXTURE
    assert endeks["date"].iloc[0] == pd.Timestamp("2025-01-01")
    assert _seri(df, "aylik_yuzde")["value"].tolist() == AYLIK_FIXTURE


def test_xlsx_aylik_satiri_yoksa_endeksten_turetilir():
    # gerçek TÜİK tablosunda aylık satır gelmezse türetme yolu çalışmalı
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Ay"
    for j, ay in enumerate(["2025-Oca", "2025-Şub", "2025-Mar"], start=2):
        ws.cell(row=1, column=j, value=ay)
    ws["A2"] = "Genel endeks (2025=100)"
    for j, v in enumerate(["98,10", "99,24", "100,90"], start=2):
        ws.cell(row=2, column=j, value=v)

    df = tuik.parse_xlsx(_wb_bytes(wb))

    aylik = _seri(df, "aylik_yuzde")
    assert len(aylik) == 2
    assert aylik["value"].iloc[0] == pytest.approx((99.24 / 98.10 - 1) * 100, rel=1e-9)


def test_xlsx_aylik_bos_hucre_endeksten_tamamlanir():
    # aylık satırın en güncel hücresi '..' ise o ay sessizce düşmemeli;
    # endeksten türetilerek tamamlanmalı (denetçi bulgusu 4)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Ay"
    for j, ay in enumerate(["2025-Oca", "2025-Şub", "2025-Mar"], start=2):
        ws.cell(row=1, column=j, value=ay)
    ws["A2"] = "Genel endeks (2025=100)"
    for j, v in enumerate(["98,10", "99,24", "100,90"], start=2):
        ws.cell(row=2, column=j, value=v)
    ws["A3"] = "Aylık değişim (%)"
    for j, v in enumerate(["1,15", "1,16", ".."], start=2):
        ws.cell(row=3, column=j, value=v)

    df = tuik.parse_xlsx(_wb_bytes(wb))

    aylik = _seri(df, "aylik_yuzde")
    assert len(aylik) == 3
    assert aylik["value"].tolist()[:2] == [1.15, 1.16]
    assert aylik["value"].iloc[-1] == pytest.approx((100.90 / 99.24 - 1) * 100, rel=1e-9)


def test_xlsx_cok_olculu_tablo_aylik_ortalama_karismaz():
    # TÜİK tablolarında 'Yıllık değişim' ve '12 aylık ortalama değişim' satırları
    # da olur; 'Aylık değişim' satırı seçilmeli, öbürleri karışmamalı (bulgu 1)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Ay"
    for j, ay in enumerate(["2025-Oca", "2025-Şub", "2025-Mar"], start=2):
        ws.cell(row=1, column=j, value=ay)
    satirlar = [
        ("Genel endeks (2025=100)", ["98,10", "99,24", "100,90"]),
        ("Aylık değişim (%)", ["1,15", "1,16", "1,67"]),
        ("Yıllık değişim (%)", ["55,00", "54,00", "53,00"]),
        ("12 aylık ortalama değişim (%)", ["40,00", "41,00", "42,00"]),
    ]
    for i, (etiket, degerler) in enumerate(satirlar, start=2):
        ws.cell(row=i, column=1, value=etiket)
        for j, v in enumerate(degerler, start=2):
            ws.cell(row=i, column=j, value=v)

    df = tuik.parse_xlsx(_wb_bytes(wb))

    assert _seri(df, "endeks")["value"].tolist() == [98.10, 99.24, 100.90]
    assert _seri(df, "aylik_yuzde")["value"].tolist() == [1.15, 1.16, 1.67]


def test_xlsx_sutun_kaybi_donen_seri_satiri_yok():
    # ne endeks ne aylık satırı: sütun kaybı -> SourceError (plan T5 step 2).
    # 3 dönem sütunu: başlık aşaması değil satır-sınıflandırma aşaması test edilsin.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Ay"
    for j, ay in enumerate(["2025-Oca", "2025-Şub", "2025-Mar"], start=2):
        ws.cell(row=1, column=j, value=ay)
    ws["A2"] = "İlgisiz gösterge"
    ws["B2"] = "1,23"
    ws["C2"] = "2,34"
    ws["D2"] = "3,45"
    with pytest.raises(SourceError):
        tuik.parse_xlsx(_wb_bytes(wb))


def test_xlsx_sutun_kaybi_donen_baslik_satiri_yok():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "rastgele"
    ws["B1"] = "kolon"
    ws["A2"] = "Genel endeks (2025=100)"
    ws["B2"] = "98,10"
    with pytest.raises(SourceError):
        tuik.parse_xlsx(_wb_bytes(wb))


def test_xlsx_bozuk_dosya_sourceerror():
    with pytest.raises(SourceError):
        tuik.parse_xlsx(b"bu bir xlsx degil")
