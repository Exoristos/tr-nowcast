"""Skor tablosu ve sonuç kalıcılığı (T14).

``summarize`` motor çıktısını pencere başına özetler; pencereler kod-sabit:
"2019→bugün" SCORE_START'tan, "son 24 ay" backtest penceresinin son
``RECENT_WINDOW_MONTHS`` ayıdır — koşu tarihine göre DEĞİL (Review Focus 5),
verideki son hedef ayına göre kaydırılır. "tam geçmiş" filtre uygulamaz.

``save_scores`` ham backtest satırlarını parquet'e tekilleştirerek yazar:
aynı (model, target_month) çiftinde yeni koşumun satırı eskisinin üzerine
geçer, diğerleri korunur (farklı --start/--end ile kısmi tekrar koşumlar
birikmeden güncellenir).

NaN'lı satırlar (ModelFailure veya actual eksik) mae/rmse/hit80 dışında
tutulur ama ``n_failed`` ile ayrıca sayılır — çökme sessizce atlanmaz.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from trnowcast import store
from trnowcast.backtest import ModelFn, run_backtest
from trnowcast.models import MODELS

# Sınav pencereleri kod-sabit (plan Global Constraints).
SCORE_START = pd.Timestamp("2019-01-01")
RECENT_WINDOW_MONTHS = 24

PENCERE_YENI = "2019→bugün"
PENCERE_SON24 = "son 24 ay"
PENCERE_TAM = "tam geçmiş"
PENCERELER = (PENCERE_YENI, PENCERE_SON24, PENCERE_TAM)

# run_backtest çıktı şeması; save_scores bu şemayı parquet'e yazar.
KOLONLAR = ["model", "target_month", "point", "lower", "upper", "actual", "abs_error", "hit80"]

HEDEF_SERI = "turkiye_tufe_aylik_yuzde"

SKOR_PARQUET_ADI = "backtest_scores.parquet"


def skor_yolu() -> Path:
    return store.DATA_ROOT / "processed" / SKOR_PARQUET_ADI


def _pencere_maske(df: pd.DataFrame, pencere: str, son_ay: pd.Timestamp) -> pd.Series:
    if pencere == PENCERE_TAM:
        return pd.Series(True, index=df.index)
    if pencere == PENCERE_YENI:
        return df["target_month"] >= SCORE_START
    # "son 24 ay": son ay dahil geriye RECENT_WINDOW_MONTHS ay.
    bas = (son_ay.to_period("M") - (RECENT_WINDOW_MONTHS - 1)).start_time
    return df["target_month"] >= bas


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Model × pencere başına mae, rmse, n, n_failed, hit80_rate özeti.

    mae/rmse/hit80_rate yalnız abs_error'ı dolu (başarılı) satırlar üzerinden;
    n_failed penceredeki NaN'lı satır sayısıdır.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["model", "window", "mae", "rmse", "n", "n_failed", "hit80_rate"]
        )

    son_ay = df["target_month"].max()
    satirlar: list[dict] = []
    for model in pd.unique(df["model"]):
        mdf = df[df["model"] == model]
        for pencere in PENCERELER:
            wdf = mdf[_pencere_maske(mdf, pencere, son_ay)]
            hatasiz = wdf["abs_error"].to_numpy(dtype=float)
            basarili = wdf[np.isfinite(hatasiz)]
            n = len(basarili)
            n_failed = len(wdf) - n
            if n:
                mae = float(basarili["abs_error"].mean())
                rmse = float(np.sqrt((basarili["abs_error"] ** 2).mean()))
                hit80_rate = float(basarili["hit80"].eq(True).mean())
            else:
                mae = rmse = hit80_rate = np.nan
            satirlar.append(
                {
                    "model": model,
                    "window": pencere,
                    "mae": mae,
                    "rmse": rmse,
                    "n": n,
                    "n_failed": n_failed,
                    "hit80_rate": hit80_rate,
                }
            )
    return pd.DataFrame(
        satirlar, columns=["model", "window", "mae", "rmse", "n", "n_failed", "hit80_rate"]
    )


def save_scores(yeni: pd.DataFrame, yol: Path | None = None) -> Path:
    """Backtest satırlarını parquet'e tekilleştirerek yazar; parquet yolunu döner.

    hit80 motor çıktısında True/False/NaN karışık object'tir; parquet için
    nullable boolean'a çevrilir (NaN → <NA>).
    """
    yol = yol or skor_yolu()
    yaz = yeni.copy()
    yaz["hit80"] = yaz["hit80"].astype("boolean")

    if yol.exists():
        eski = pd.read_parquet(yol)
        eski["hit80"] = eski["hit80"].astype("boolean")
        anahtarlar = set(zip(yaz["model"], yaz["target_month"]))
        mask = pd.Series(
            [
                (m, t) not in anahtarlar
                for m, t in zip(eski["model"], eski["target_month"])
            ],
            index=eski.index,
        )
        birlesik = pd.concat([eski[mask], yaz], ignore_index=True)
    else:
        birlesik = yaz
    birlesik = birlesik.sort_values(["model", "target_month"], kind="stable")

    yol.parent.mkdir(parents=True, exist_ok=True)
    # T2 deposuyla aynı atomik yazım (tmp + os.replace).
    tmp = yol.with_name(yol.name + ".tmp")
    birlesik.to_parquet(tmp, index=False)
    os.replace(tmp, yol)
    return yol


def backtest_kos(
    start: str | None = None,
    end: str | None = None,
    models: dict[str, ModelFn] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Seçilen modellerle backtest koşar, skorları kalıcı parquet'e yazar.

    models verilmezse tüm arena (MODELS — 8 yarışmacı, T19) koşar; CLI
    ``--models`` seçimini sözlük olarak geçirir. Varsayılanlar: start =
    SCORE_START (2019-01), end = hedef serideki son aylık değerin ayı.
    Döner: (ham sonuçlar, summarize tablosu). ModelFailure normal iş
    akışıdır; burada ve çağıran CLI'da exit 0'dır.
    """
    if models is None:
        models = MODELS
    if end is None:
        end = store.load_series(HEDEF_SERI)["date"].max().to_period("M").start_time
    if start is None:
        start = SCORE_START
    sonuclar = run_backtest(models, HEDEF_SERI, pd.Timestamp(start), pd.Timestamp(end))
    save_scores(sonuclar)
    return sonuclar, summarize(sonuclar)


def _sayi(x: float) -> str:
    return "-" if pd.isna(x) else f"{x:.3f}"


def tablo_satirlari(tablo: pd.DataFrame) -> list[tuple[str, ...]]:
    """summarize çıktısını hizalanmaya hazır metin satırlarına çevirir."""
    satirlar: list[tuple[str, ...]] = [
        ("model", "pencere", "mae", "rmse", "n", "n_failed", "hit80")
    ]
    for _, r in tablo.iterrows():
        satirlar.append(
            (
                str(r["model"]),
                str(r["window"]),
                _sayi(r["mae"]),
                _sayi(r["rmse"]),
                str(int(r["n"])),
                str(int(r["n_failed"])),
                _sayi(r["hit80_rate"]),
            )
        )
    return satirlar
