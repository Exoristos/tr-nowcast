"""T20 nowcast/export testleri için ortak yardımcılar — test_nowcast.py ve
test_export.py kullanır.

pytest'in prepend import modunda tests/ dizini sys.path'e eklendiğinden bu
modül `from nowcast_araclari import ...` ile içe aktarılır; adı test_ öneki
taşımadığı için test toplamasına girmez. Fixture'lar burada TANIMLANMAZ:
mevcut test stili fixture'ları her test dosyası içinde kurar.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from trnowcast.scoring import HEDEF_SERI
from trnowcast.store import SeriesMeta, save_series

# Sabit koşum anı: testler nowcast._simdi'yi buna sabitler (şema + idempotentlik).
SABIT_AN = datetime(2026, 6, 15, 10, 30, tzinfo=UTC)


def make_meta(**overrides) -> SeriesMeta:
    defaults = {
        "name": "test_serisi",
        "source": "test",
        "url": "https://example.org/veri.csv",
        "frequency": "aylık",
        "units": "yuzde",
        "publication_lag_days": 3,
        "license_note": "lisans: test",
    }
    defaults.update(overrides)
    return SeriesMeta(**defaults)


def make_df(dates, values, series_id: str) -> pd.DataFrame:
    # PeriodIndex verilirse ay-başı timestamp'lere indirgenir (yeni pandas kabul etmez).
    if isinstance(dates, pd.PeriodIndex):
        dates = dates.to_timestamp()
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "value": values, "series_id": series_id}
    )


def tufe_serisi_kaydet() -> None:
    """14 aylık hedef seri (2025-04…2026-05); son 11 gerçek ayın hepsi %1.0."""
    aylar = pd.period_range("2025-04", "2026-05", freq="M")
    save_series(
        make_meta(name=HEDEF_SERI),
        make_df(aylar, [1.0] * len(aylar), HEDEF_SERI),
    )
