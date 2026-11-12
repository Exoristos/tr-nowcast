"""Parquet depo ve as-of registry (Faz 0 / T2).

Kaynak modüllerinin ürettiği long-format serileri ``data/processed/{name}.parquet``
altında saklar; her serinin kaynak üstverisini ``data/processed/registry.json``
içine name-keyed upsert eder.

Kaynak URL'i bu modülde sabit değildir: her kaynak modülü (FRED, FAO, TÜİK, EVDS)
gerçek veri URL'ini ve erişim bilgisini ``SeriesMeta.url`` / ``SeriesMeta.source``
ile buraya verir; registry bu bilgiyi ``last_fetched`` ISO zaman damgasıyla kalıcı
kılar (dürüstlük sözleşmesi md. 2: her serinin yayın takvimi kayıt altındadır).

Şema (long format): ``date`` (datetime64), ``value`` (float), ``series_id`` (str).
Upsert semantiği: yeni DataFrame mevcut parquet ile birleştirilir; aynı
(series_id, date) çiftinde birden çok satırsa son gelen değer kazanır (revize
değerler eskiyi ezer); farklı seriler aynı tarihte olsa çökertilmez. Sonuç
(series_id, date) artan sırada yazılır. Parquet ve registry yazımları
atomiktir (tmp + os.replace).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

# src layout: src/trnowcast/store.py -> depo kökü iki üst dizin.
# Testler bu modül değişkenini tmp_path'e yönlendirir (offline izolasyon).
DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

REQUIRED_COLUMNS = ("date", "value", "series_id")
VALID_FREQUENCIES = ("aylık", "günlük")


@dataclass
class SeriesMeta:
    """Bir serinin kaynak üstverisi; registry.json girdisine aynen yazılır."""

    name: str
    source: str
    url: str
    frequency: str  # "aylık" | "günlük"
    units: str
    publication_lag_days: int
    license_note: str
    nan_threshold: float = 0.05
    # Değer aralığı uyarı eşiği (alt, üst); quality kontrolü bunu okur, kod
    # tablosu tutmaz. Eşiği seri tanımlandığı kaynak modülü verir; None →
    # seriye aralık kontrolü uygulanmaz.
    warn_range: tuple[float, float] | None = None

    def __post_init__(self):
        if self.frequency not in VALID_FREQUENCIES:
            raise ValueError(
                f"frekans '{self.frequency}' geçersiz; beklenen: {VALID_FREQUENCIES}"
            )
        if (
            self.warn_range is not None
            and (
                len(self.warn_range) != 2 or self.warn_range[0] > self.warn_range[1]
            )
        ):
            raise ValueError(
                f"warn_range '{self.warn_range}' geçersiz; beklenen (alt, üst) "
                "şeklinde iki sayı, alt <= üst"
            )


def _processed_dir() -> Path:
    return DATA_ROOT / "processed"


def _parquet_path(name: str) -> Path:
    return _processed_dir() / f"{name}.parquet"


def _registry_path() -> Path:
    return _processed_dir() / "registry.json"


def _coerce(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Şema sözleşmesini uygula: zorunlu sütunlar + date/value tipi."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{name}: şema hatası — eksik sütun(lar): {missing}; "
            f"beklenen: {list(REQUIRED_COLUMNS)}"
        )
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["value"] = out["value"].astype(float)
    return out


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _atomic_write_json(payload: dict, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def save_series(meta: SeriesMeta, df: pd.DataFrame) -> Path:
    """Seriyi parquet'e upsert eder, registry'yi günceller; parquet yolunu döner."""
    new = _coerce(df, meta.name)
    processed = _processed_dir()
    processed.mkdir(parents=True, exist_ok=True)
    path = _parquet_path(meta.name)

    if path.exists():
        # Yeni satırlar sonda: aynı (series_id, date) için son gelen (revize) değer kazanır.
        old = pd.read_parquet(path)
        new = pd.concat([old, new], ignore_index=True)
    merged = (
        new.drop_duplicates(subset=["series_id", "date"], keep="last")
        .sort_values(["series_id", "date"], kind="stable")
        .reset_index(drop=True)
    )
    _atomic_write_parquet(merged, path)

    entry = asdict(meta) | {"last_fetched": datetime.now(UTC).isoformat()}
    reg = registry()
    reg[meta.name] = entry
    _atomic_write_json(reg, _registry_path())
    return path


def load_series(name: str) -> pd.DataFrame:
    """Saklı seriyi okur; seri yoksa KeyError fırlatır."""
    path = _parquet_path(name)
    if not path.exists():
        raise KeyError(f"seri bulunamadı: {name} ({path} yok)")
    return pd.read_parquet(path)


def registry() -> dict[str, dict]:
    """registry.json içeriği; dosya henüz yoksa boş sözlük döner."""
    path = _registry_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
