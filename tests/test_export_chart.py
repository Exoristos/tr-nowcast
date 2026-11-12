"""export T25 genişletmesi — chart.json, 12 aylık gerçek özet, assets_root kopyası.

Tamamen offline: skor parquet'i sentetik satırlarla kurulur, arena koşum yok
(taze işaret nowcast.json verilir). Beklenen değerler bu kurulumdan ELLE
hesaplandı — test içi yeniden hesap yok; medyan, agregasyon ve pencere sınırı
gerçekten sınanır.

Arena: aylar 2024-05…2026-07 (27 ay; 12 aylık pencere i=15…26), gerçek döngü
PAT = (1.0, 1.5, 2.0, 1.0, 0.5, 1.0, 1.5) — farklar hiç sıfır değil. Modeller:
a = gerçek + işaret(fark)·e, e = 0.3+0.1·(i mod 3) → yön %100, pencere MAE
0.4, bant ±1.0 (hit80 True); i=14 (pencere DIŞI) çöker. b = önceki gerçek
− işaret(fark)·0.5 → yön %0, pencere MAE 13/12, bant çift i'de ±2.0 (hit80
True), tek i'de ±0.1 (False). d = gerçek (MAE 0, yön %100), bant ±0.3 (True);
i=0'da çöker. c her ay çöker — NaN satırlar hiçbir istatistiğe girmez; i=0'da
hepsi NaN. Pencere özeti (havuz): median_mae_12m = median(0.4, 13/12, 0.0) =
0.4; yön 24/36 = 2/3 (a+d isabetli); bant içi 30/36 = 5/6. Chart: i=0 null'lar;
i=14 (yalnız b+d) medyan 1.5, bant 0.35–2.65; son ay (b geniş) 1.0, 0.5–2.0.
"""

import hashlib
import inspect
import json

import numpy as np
import pandas as pd
import pytest
from nowcast_araclari import SABIT_AN, make_df, make_meta

from trnowcast import store
from trnowcast.export import export_site
from trnowcast.scoring import HEDEF_SERI, skor_yolu
from trnowcast.store import save_series

PAT = (1.0, 1.5, 2.0, 1.0, 0.5, 1.0, 1.5)
AYLAR = pd.period_range("2024-05", "2026-07", freq="M")

# Taze işaret nowcast: _nowcast_bolumu bunu yayımlar, arena KOŞMAZ (offline).
ISARET_NOWCAST = {
    "generated_at": "2026-06-15", "cutoff_date": "2026-06-15", "target_month": "2026-06",
    "forecasts": [], "yillik": None,
}


def _arena_satirlari() -> pd.DataFrame:
    satirlar = []
    for i, ay in enumerate(AYLAR):
        g = PAT[i % 7]
        if i:
            fark = g - PAT[(i - 1) % 7]
            s = (fark > 0) - (fark < 0)
        else:
            fark, s = 0.0, 0  # i=0: önceki gerçek parquet'te yok
        if i in (0, 14):
            a = (np.nan, np.nan, np.nan, np.nan)
        else:
            p = g + s * (0.3 + 0.1 * (i % 3))
            a = (p, p - 1.0, p + 1.0, True)
        if i == 0:
            b = (np.nan, np.nan, np.nan, np.nan)
        else:
            p = PAT[(i - 1) % 7] - 0.5 * s
            yarim = 2.0 if i % 2 == 0 else 0.1
            b = (p, p - yarim, p + yarim, i % 2 == 0)
        d = (np.nan, np.nan, np.nan, np.nan) if i == 0 else (g, g - 0.3, g + 0.3, True)
        for ad, (p, lo, hi, hit) in (("a", a), ("b", b), ("c", (np.nan,) * 4), ("d", d)):
            satirlar.append(
                {
                    "model": ad,
                    "target_month": ay.start_time,
                    "point": p,
                    "lower": lo,
                    "upper": hi,
                    "actual": g,
                    "abs_error": np.nan if np.isnan(p) else abs(p - g),
                    "hit80": hit,
                }
            )
    return pd.DataFrame(satirlar)


def _parquet_yaz(satirlar: pd.DataFrame) -> None:
    """Skor parquet'ini doğrudan yazar (arena koşumu / birleştirme yok)."""
    yol = skor_yolu()
    yol.parent.mkdir(parents=True, exist_ok=True)
    yaz = satirlar.copy()
    yaz["hit80"] = yaz["hit80"].astype("boolean")
    yaz.to_parquet(yol, index=False)


def _kucuk_parquet(aylar, actual, point) -> pd.DataFrame:
    """Yön testleri için tek model (a), dar bantlı minimal parquet satırları."""
    return pd.DataFrame(
        {
            "model": ["a"] * len(aylar),
            "target_month": pd.to_datetime(aylar),
            "point": point,
            "lower": [p - 0.3 for p in point],
            "upper": [p + 0.3 for p in point],
            "actual": actual,
            "abs_error": [abs(p - a) for p, a in zip(point, actual)],
            "hit80": [True] * len(aylar),
        }
    )


@pytest.fixture
def depo(tmp_path, monkeypatch):
    """Tmp veri kökü + beş site serisi + sentetik arena parquet'i + taze nowcast."""
    root = tmp_path / "data"
    monkeypatch.setattr(store, "DATA_ROOT", root)
    monkeypatch.setattr("trnowcast.nowcast._simdi", lambda: SABIT_AN)

    aylar = pd.period_range("2025-04", "2026-05", freq="M")
    save_series(make_meta(name=HEDEF_SERI), make_df(aylar, [1.0] * len(aylar), HEDEF_SERI))
    for ad, deger in (("fao_gida_endeks", 120.0), ("tufe_beklenti_pka", 24.0)):
        save_series(
            make_meta(name=ad, publication_lag_days=0),
            make_df(aylar, [deger] * len(aylar), ad),
        )
    for ad, deger in (("usd_try_gunluk", 38.0), ("brent_gunluk", 80.0)):
        gunler = pd.bdate_range("2026-03-02", "2026-06-10")
        save_series(
            make_meta(name=ad, frequency="günlük", publication_lag_days=0),
            make_df(gunler, [deger] * len(gunler), ad),
        )

    _parquet_yaz(_arena_satirlari())

    isaret_yolu = root / "processed" / "nowcast.json"
    isaret_yolu.parent.mkdir(parents=True, exist_ok=True)
    isaret_yolu.write_text(json.dumps(ISARET_NOWCAST), encoding="utf-8")
    return root


def site_yolu():
    return store.DATA_ROOT / "site"


def _oku(ad: str) -> dict:
    return json.loads((site_yolu() / ad).read_text(encoding="utf-8"))


def _hashler(site) -> dict[str, str]:
    return {
        str(y.relative_to(site)): hashlib.sha256(y.read_bytes()).hexdigest()
        for y in sorted(site.rglob("*.json"))
    }


# --- chart.json ---------------------------------------------------------------


def test_chart_semasi_ve_arena_medyan(depo):
    export_site()
    chart = _oku("chart.json")
    assert list(chart) == ["months", "actual", "forecast_median", "band_lo", "band_hi", "windows"]
    assert len(chart["months"]) == 27
    assert chart["months"][0] == "2024-05-01" and chart["months"][-1] == "2026-07-01"
    # i=0: tüm modeller NaN → medyan/bant null; actual yine dolu (NaN yasak).
    assert chart["actual"][0] == pytest.approx(1.0)
    assert chart["forecast_median"][0] is None
    assert chart["band_lo"][0] is None and chart["band_hi"][0] is None
    # i=14 (2025-07): a çöktü → medyan yalnız b+d'den (elle: 1.5 / 0.35 / 2.65).
    i = chart["months"].index("2025-07-01")
    assert chart["forecast_median"][i] == pytest.approx(1.5)
    assert chart["band_lo"][i] == pytest.approx(0.35)
    assert chart["band_hi"][i] == pytest.approx(2.65)
    # Son ay: üç modelin medyanı (elle: 1.0 / 0.5 / 2.0 — b geniş bantlı).
    assert chart["forecast_median"][-1] == pytest.approx(1.0)
    assert chart["band_lo"][-1] == pytest.approx(0.5)
    assert chart["band_hi"][-1] == pytest.approx(2.0)
    assert "NaN" not in (site_yolu() / "chart.json").read_text(encoding="utf-8")


def test_chart_pencereleri(depo):
    export_site()
    w = _oku("chart.json")["windows"]
    assert list(w) == ["m12", "m24", "all"]
    assert len(w["m12"]) == 12
    assert w["m12"][0] == "2025-08-01" and w["m12"][-1] == "2026-07-01"
    assert len(w["m24"]) == 24 and w["m24"][0] == "2024-08-01"
    assert w["all"] == _oku("chart.json")["months"]


# --- scores.json 12 aylık gerçek özet ------------------------------------------


def test_scores_12m_gercek_ozet(depo):
    export_site()
    skor = _oku("scores.json")
    assert list(skor) == [
        "generated_at", "windows", "scores",
        "median_mae_12m", "yon_isabet_12m", "bant_icinde_12m",
    ]
    assert skor["median_mae_12m"] == pytest.approx(0.4)
    assert skor["yon_isabet_12m"] == {"dogru": 24, "toplam": 36, "oran": pytest.approx(2 / 3)}
    assert skor["bant_icinde_12m"] == pytest.approx(5 / 6)


def test_yon_onceki_gercek_yoksa_sayilmaz(depo):
    # 2026-02 hiç yok: 2026-03'ün önceki gerçeği parquet'te yok → satır sayılmaz.
    _parquet_yaz(
        _kucuk_parquet(
            ["2025-11-01", "2025-12-01", "2026-01-01", "2026-03-01"],
            [1.0, 1.0, 0.5, 0.5],
            [1.2, 1.2, 0.8, 0.9],
        )
    )
    export_site()
    # 2025-11: önceki gerçek yok → hariç; 2025-12: 1.2 vs sabit → ıskalama;
    # 2026-01: 0.8, gerçek düşüş → isabet; 2026-03: önceki gerçek yok → hariç.
    assert _oku("scores.json")["yon_isabet_12m"] == {"dogru": 1, "toplam": 2, "oran": 0.5}


def test_yon_toplam_sifirsa_oran_null(depo):
    _parquet_yaz(_kucuk_parquet(["2026-01-01"], [1.0], [1.2]))
    export_site()
    yon = _oku("scores.json")["yon_isabet_12m"]
    assert yon["toplam"] == 0 and yon["oran"] is None


# --- assets_root kopyası -------------------------------------------------------


def test_assets_root_kopya(depo, tmp_path):
    kopya = tmp_path / "assets_root"
    yollar = export_site(assets_root=kopya)
    site = site_yolu()
    for y in yollar:
        hedef = kopya / y.relative_to(site)
        assert hedef.is_file()
        assert hedef.read_bytes() == y.read_bytes()
    assert (kopya / "series" / "tufe_aylik.json").is_file()


def test_assets_root_varsayilan_kapali(depo):
    # Varsayılan kapalı: yalnız CI/deploy parametreyle açar (plan T25).
    varsayilan = inspect.signature(export_site).parameters["assets_root"].default
    assert varsayilan is None


# --- Review Focus 4: idempotentlik (chart.json dahil tüm site dosyaları) -------


def test_idempotentlik_iki_kosum_ayni_bayt(depo):
    export_site()
    birinci = _hashler(site_yolu())
    assert birinci  # gerçekten dosya toplandı
    export_site()
    assert birinci == _hashler(site_yolu())
