"""TCMB PKA anket benchmark'ı (T18) — model arenasının dış yarışmacısı.

Seri: ``tufe_beklenti_pka`` — PKA "Cari Ayın Aylık TÜFE Beklentisi" sorusunun
uygun ortalaması (medyan değil; kaynak modülü ``sources/survey.py`` kaydı).
Hedef seriyle aynı soru olduğu için tahmin değil doğrudan gözlemlenmiş
beklenti olarak tabloya girer.

Hizalama (Review Focus 5): hedef ay M için M anket satırı okunur. Anketin
yayın gecikmesi 0 gün olduğu için motor kesiti M sonu + 2 günde kurar ve M
anketi kesitte yayındadır; M satırı yoksa ModelFailure — komşu ayın satırı
sessizce kullanılmaz (yanlış hizalama sessiz skor üretmez).

Bant: tarihsel |gerçek − anket| hatalarının %80 persentili; hatalar yalnız
kesitteki veriden hesaplanır (kesit dışı actual'a erişim yok) ve 0.2'nin
altına düşmez.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trnowcast.backtest import ForecastPoint, ModelFailure

ANKET_SERISI = "tufe_beklenti_pka"
MODEL_ADI = "anket_pka"

# Bant tabanı: dar bant aşırı güven verir (baseline.py ile aynı kural).
BANT_TABANI = 0.2


def _kesit_df(kesit: dict[str, pd.DataFrame], seri: str) -> pd.DataFrame:
    df = kesit.get(seri)
    if df is None or df.empty:
        raise ModelFailure(f"{MODEL_ADI}: seri kesitte yok veya boş ({seri})")
    return df


def ANKET_PKA(
    kesit: dict[str, pd.DataFrame],
    hedef_ay: pd.Timestamp,
    target: str,
) -> ForecastPoint:
    """Hedef ay M için M anket satırını nokta tahmin olarak döndürür."""
    anket_df = _kesit_df(kesit, ANKET_SERISI)
    hedef_df = _kesit_df(kesit, target)

    ay = pd.Period(hedef_ay, freq="M").start_time
    if ay not in anket_df.index:
        raise ModelFailure(
            f"{MODEL_ADI}: {ay:%Y-%m} anket satırı kesitte yok — "
            "komşu ay satırı kullanılmaz (Review Focus 5)"
        )
    nokta = float(anket_df.loc[ay, "value"])
    if not np.isfinite(nokta):
        raise ModelFailure(f"{MODEL_ADI}: {ay:%Y-%m} anket değeri NaN/inf")

    birlesik = pd.concat(
        {"hedef": hedef_df["value"], "anket": anket_df["value"]}, axis=1, join="inner"
    ).dropna()
    if birlesik.empty:
        raise ModelFailure(f"{MODEL_ADI}: hedef–anket ortuşmesi boş, bant hesaplanamaz")
    hatalar = (birlesik["hedef"] - birlesik["anket"]).abs().to_numpy()
    bant = max(float(np.percentile(hatalar, 80)), BANT_TABANI)
    return ForecastPoint(
        target_month=ay, point=nokta, lower=nokta - bant, upper=nokta + bant, model=MODEL_ADI
    )
