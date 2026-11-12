"""T7 CLI testleri için ortak yardımcılar — test_cli.py ve test_cli_durum.py kullanır.

pytest'in prepend import modunda tests/ dizini sys.path'e eklendiğinden bu modül
`from cli_test_araclari import ...` ile içe aktarılır; adı test_ öneki taşımadığı
için test toplamasına girmez.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from trnowcast.sources import SourceError
from trnowcast.store import SeriesMeta, save_series


def meta(name: str) -> SeriesMeta:
    return SeriesMeta(
        name=name,
        source="TestKaynak",
        url="https://ornek.test/veri.csv",
        frequency="aylık",
        units="test birimi",
        publication_lag_days=1,
        license_note="test kapsamı",
    )


def seri_df(name: str, values=(1.0, 2.0)) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(values), freq="MS"),
            "value": [float(v) for v in values],
            "series_id": name,
        }
    )


def kaydet(name: str, values=(1.0, 2.0), **meta_ek) -> None:
    save_series(replace(meta(name), **meta_ek), seri_df(name, values))


def kaynak_sahtesi(name: str):
    def sahte():
        return [save_series(meta(name), seri_df(name))]

    return sahte


def hata(mesaj: str):
    # *_args: fred/fao/tuik fetch_all() argümansız, evds/anket fetch_all(anahtar) çağrılır
    def sahte(*_args):
        raise SourceError(mesaj)

    return sahte
