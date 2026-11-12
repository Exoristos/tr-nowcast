"""Site veri ihracı (T20, T25) — statik JSON seti ``data/site`` altına yazılır.

Worker (T22) bu dosyaları asset olarak servis eder; veri güncellemesi = yeni
commit. Review Focus 4: iki üst üste koşum aynı baytları üretmeli — tüm
sıralamalar deterministik, alan sıraları sabit; zaman damgaları
``nowcast._simdi``'den gelir (aynı koşum anında aynı bayt). NaN'lı metrikler
JSON'da null olur; ``json_metni``'nin allow_nan=False koruması sessiz bozuk
JSON'u engeller.

T25 ekleri: ``chart.json`` (arena medyanı + bant uçları), scores.json'un 12
aylık gerçek özeti ve ``assets_root`` kopyası (parametreli, varsayılan kapalı).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from trnowcast import store
from trnowcast.nowcast import json_metni, kesit_gunu, nowcast_kos
from trnowcast.scoring import PENCERELER, skor_yolu, summarize

# scores.json'un 12 aylık gerçek özet penceresi (son hedef ayı dahil geriye).
SON12_AY = 12

# Siteye ihraç edilen seriler: (dosya adı, depo serisi adı) — sabit sıra.
SITE_SERILERI: tuple[tuple[str, str], ...] = (
    ("tufe_aylik", "turkiye_tufe_aylik_yuzde"),
    ("usd_aylik", "usd_try_gunluk"),
    ("brent_aylik", "brent_gunluk"),
    ("fao_aylik", "fao_gida_endeks"),
    ("anket_pka", "tufe_beklenti_pka"),
)


def _nowcast_bolumu() -> dict:
    """Yayınlanacak nowcast bölümü: taze dosya varsa yeniden koşum YOK.

    'trnowcast nowcast' data/processed/nowcast.json'a yazar; export aynı kesit
    gününe ait dosyayı aynen yayınlar — CI akışında (T21: nowcast → export)
    8 modellik arena ve TSFM çıkarımı tek kez koşar, iki kopya bit-bit tutarlı
    kalır. Dosya yoksa, bozuksa veya cutoff_date bugünden eskiyse taze koşum
    üretilir.
    """
    yol = store.DATA_ROOT / "processed" / "nowcast.json"
    if yol.exists():
        try:
            mevcut = json.loads(yol.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            mevcut = None
        if isinstance(mevcut, dict) and mevcut.get("cutoff_date") == kesit_gunu():
            return mevcut
    return nowcast_kos()


def export_site(out_dir: Path | None = None, assets_root: Path | None = None) -> list[Path]:
    """Site veri setini yazar; yazılan dosya yollarını sıralı döndürür.

    out_dir verilmezse ``data/site`` kullanılır. nowcast.json, ``_nowcast_bolumu``
    çıktısıdır (varsayılan arena; çöken model ihraç kırmaz — Review Focus 3).
    assets_root verilirse yazılan dosyalar aynı göreli yapıyla oraya da
    kopyalanır (T25; varsayılan kapalı, CI/deploy parametreyle açar).
    """
    hedef = out_dir or store.DATA_ROOT / "site"
    nowcast = _nowcast_bolumu()
    uretim = nowcast["generated_at"]
    cutoff = pd.Timestamp(nowcast["cutoff_date"])
    skor_df = _skor_df()

    hedef.mkdir(parents=True, exist_ok=True)
    yazilan = [
        _yaz(hedef / "nowcast.json", nowcast),
        _yaz(hedef / "scores.json", _scores(skor_df, uretim)),
        _yaz(hedef / "meta.json", _meta(uretim)),
        _yaz(hedef / "chart.json", _chart(skor_df)),
    ]
    seriler = hedef / "series"
    seriler.mkdir(exist_ok=True)
    for dosya_adi, seri in SITE_SERILERI:
        yazilan.append(_yaz(seriler / f"{dosya_adi}.json", _seri_json(seri, cutoff)))
    if assets_root is not None:
        kok = Path(assets_root)
        for y in yazilan:
            kopya = kok / y.relative_to(hedef)
            kopya.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(y, kopya)
    return sorted(yazilan)


def _yaz(path: Path, payload) -> Path:
    path.write_text(json_metni(payload), encoding="utf-8")
    return path


def _sayi(deger) -> float | None:
    """NaN/None → None; JSON'da NaN yasak, sessiz bozuk değer yok."""
    x = float(deger)
    return x if pd.notna(x) else None


def _skor_df() -> pd.DataFrame:
    """Skor parquet'ini okur; yoksa yönlendirici hata (chart da aynı kaynağı kullanır)."""
    yol = skor_yolu()
    if not yol.exists():
        raise FileNotFoundError(
            f"skor parquet'i yok: {yol} — önce 'trnowcast backtest' çalıştırın"
        )
    return pd.read_parquet(yol)


def _scores(skor_df: pd.DataFrame, uretim: str) -> dict:
    """Faz 1 summarize tablosunun üç penceresi + T25'in 12 aylık gerçek özeti
    (tanım ``_ozet_12m``'de); NaN metrikler null olur (JSON'da NaN yasak).
    """
    tablo = summarize(skor_df)
    satirlar = sorted(
        (
            {
                "model": str(r["model"]),
                "window": str(r["window"]),
                "mae": _sayi(r["mae"]),
                "rmse": _sayi(r["rmse"]),
                "n": int(r["n"]),
                "n_failed": int(r["n_failed"]),
                "hit80_rate": _sayi(r["hit80_rate"]),
            }
            for _, r in tablo.iterrows()
        ),
        key=lambda s: (s["model"], s["window"]),
    )
    skor = {"generated_at": uretim, "windows": list(PENCERELER), "scores": satirlar}
    skor.update(_ozet_12m(skor_df))
    return skor


def _chart(skor_df: pd.DataFrame) -> dict:
    """chart.json (T25): grafik serisi, kaynak backtest_scores.parquet.

    Ay başına: actual (gerçek), forecast_median = arenanın point medyanı,
    band_lo/band_hi = hit80 bant uçlarının (lower/upper) arena medyanı. NaN'lı
    model satırları medyana girmez; ayda hiç finite değer yoksa alan null olur
    (NaN yasak). windows: m12/m24 = ay listesinin son N'i, all tamamı.
    """
    df = skor_df.sort_values(["target_month", "model"], kind="stable")
    aylar = sorted(pd.unique(df["target_month"]))
    iso = [pd.Timestamp(a).strftime("%Y-%m-%d") for a in aylar]
    gr = df.groupby("target_month", sort=False)

    def medyanlar(kolon: str) -> list[float | None]:
        med = gr[kolon].median()
        return [_sayi(med.get(a)) for a in aylar]

    return {
        "months": iso,
        "actual": medyanlar("actual"),
        "forecast_median": medyanlar("point"),
        "band_lo": medyanlar("lower"),
        "band_hi": medyanlar("upper"),
        "windows": {"m12": iso[-SON12_AY:], "m24": iso[-24:], "all": iso},
    }


def _isaret(x: float) -> int:
    return (x > 0) - (x < 0)


def _ozet_12m(df: pd.DataFrame) -> dict:
    """scores.json'un 12 aylık gerçek özet alanları (T25) — parquet'ten.

    Pencere: son hedef ayı dahil geriye 12 ay (veri sonuna göre; scoring
    pencereleriyle aynı ilke — koşum tarihine göre değil).
    - median_mae_12m: pencerede model başına MAE, arenada medyan.
    - yon_isabet_12m: Review Focus 3 tanımı — isabet = işaret(tahmin −
      önceki_gerçek) == işaret(gerçek − önceki_gerçek). Önceki gerçek
      parquet'in kendi actual sütunundan (hedef ay − 1) alınır; o ay
      parquet'te yoksa veya NaN'sa satır sayıma girmez. Arena genelinde
      havuzlanır (n/n + oran).
    - bant_icinde_12m: pencerede abs_error'ı dolu satırlarda hit80 oranı
      (havuzlanmış; başarısız satırlar paya da paydaya girmez).
    """
    son = df["target_month"].max()
    bas = (son.to_period("M") - (SON12_AY - 1)).start_time
    w = df[(df["target_month"] >= bas) & (df["target_month"] <= son)]

    mae = w.dropna(subset=["abs_error"]).groupby("model")["abs_error"].mean()
    median_mae = _sayi(mae.median()) if len(mae) else None

    gercek = dict(zip(df["target_month"], df["actual"]))
    dogru = toplam = 0
    for _, r in w.iterrows():
        onceki = gercek.get((r["target_month"].to_period("M") - 1).start_time)
        if not (np.isfinite(r["point"]) and pd.notna(r["actual"]) and pd.notna(onceki)):
            continue
        dogru += _isaret(r["point"] - onceki) == _isaret(r["actual"] - onceki)
        toplam += 1
    oran = _sayi(dogru / toplam) if toplam else None

    basarili = w[np.isfinite(w["abs_error"].to_numpy(dtype=float))]
    bant = _sayi(basarili["hit80"].eq(True).mean()) if len(basarili) else None

    return {
        "median_mae_12m": median_mae,
        "yon_isabet_12m": {"dogru": dogru, "toplam": toplam, "oran": oran},
        "bant_icinde_12m": bant,
    }


def _aylik_noktalar(seri: str, cutoff: pd.Timestamp) -> pd.Series:
    """Site gösterimi için aylık değerler; yayın kuralı asof_monthly ile aynı.

    Neden asof_monthly değil: oradaki 'tam ay = tüm takvim günleri' kuralı
    backtest kesitinin sızıntı güvencesidir; iş günü serilerinde (usd_try_gunluk,
    brent_gunluk — ayda ~20-22 satır) hiçbir ay bu koşulu sağlamaz ve gösterim
    serisi kalıcı boş kalır. Gösterimde günlük seri için koşul 'ay bitmiş'tir
    (ay sonu + lag ≤ cutoff): ayın mevcut günlerinin ortalaması aylık değerdir.
    Bu yol tahmin kesiti DEĞİLDİR — Review Focus 1 yalnız nowcast kesitini bağlar.
    """
    meta = store.registry()[seri]
    lag = int(meta["publication_lag_days"])
    df = store.load_series(seri).sort_values("date", kind="stable")
    ay = df["date"].dt.to_period("M")
    yayinda = ay.dt.end_time.dt.normalize() + pd.Timedelta(days=lag) <= cutoff
    df, ay = df.loc[yayinda], ay.loc[yayinda]
    if df.empty:
        return pd.Series(dtype=float)
    if meta["frequency"] == "günlük":
        return df.groupby(ay)["value"].mean()
    return df.groupby(ay)["value"].last()


def _seri_json(seri: str, cutoff: pd.Timestamp) -> dict:
    """Seri kesitini ay-başı ISO + kayan nokta noktalarına çevirir."""
    degerler = _aylik_noktalar(seri, cutoff).sort_index()
    birim = store.registry()[seri]["units"]
    noktalar = [
        [p.start_time.strftime("%Y-%m-%d"), float(deger)] for p, deger in degerler.items()
    ]
    return {"series": seri, "unit": birim, "points": noktalar}


def _meta(uretim: str) -> dict:
    reg = store.registry()
    return {
        "generated_at": uretim,
        "registry": {ad: reg[ad] for ad in sorted(reg)},
    }
