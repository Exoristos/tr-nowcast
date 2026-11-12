"""Benchmark modelleri: ortak ModelFn imzası, motoru besleyen arena sözlüğü.

MODELS — 8 yarışmacı (T19): Faz 1 klasik dörtlüsü (CLASSIC) + T15-T18'in dört
yeni oyuncusu (chronos2_uni, timesfm3_mv, bridge, anket_pka). TSFM modülleri
ağır kütüphaneyi (torch/timesfm) fonksiyon içinde lazy yüklediği için bu
paketin içe aktarımı model ağırlığı indirmez; CLI'ın diğer komutları etkilenmez.
"""

from trnowcast.models.baseline import naive, seasonal_naive
from trnowcast.models.bridge import BRIDGE
from trnowcast.models.classic import arima, ets
from trnowcast.models.survey_bench import ANKET_PKA
from trnowcast.models.tsfm_chronos import CHRONOS2_UNI
from trnowcast.models.tsfm_timesfm import TIMESFM3_MV

# Faz 1 klasik dörtlüsü: backtest --models classic yalnız bunları koşar.
CLASSIC = ("naive", "seasonal_naive", "arima", "ets")

# run_backtest'e doğrudan geçilebilir: 8 yarışmacının tamamı.
MODELS = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "arima": arima,
    "ets": ets,
    "chronos2_uni": CHRONOS2_UNI,
    "timesfm3_mv": TIMESFM3_MV,
    "bridge": BRIDGE,
    "anket_pka": ANKET_PKA,
}

__all__ = [
    "CLASSIC",
    "MODELS",
    "arima",
    "ets",
    "modeller_sec",
    "naive",
    "seasonal_naive",
]


def modeller_sec(secim: str) -> dict:
    """CLI --models değerini ModelFn sözlüğüne çevirir.

    'all' → tüm arena, 'classic' → Faz 1 dörtlüsü, virgüllü liste → verilen
    adlar (MODELS sırası korunur). Bilinmeyen ad ValueError fırlatır; CLI bunu
    click.BadParameter'a çevirir (models paketi click'e bağımlı kalmaz).
    """
    if secim == "all":
        return dict(MODELS)
    if secim == "classic":
        return {ad: MODELS[ad] for ad in CLASSIC}
    adlar = [ad.strip() for ad in secim.split(",") if ad.strip()]
    if not adlar:
        raise ValueError("model listesi boş")
    bilinmeyen = [ad for ad in adlar if ad not in MODELS]
    if bilinmeyen:
        raise ValueError(f"bilinmeyen model: {', '.join(bilinmeyen)}")
    return {ad: MODELS[ad] for ad in adlar}
