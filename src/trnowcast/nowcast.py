"""Canlı nowcast ve türetilmiş yıllık (T20) — backtest motorunun tek-koşum modu.

Hedef ay = ``turkiye_tufe_aylik_yuzde`` serisinin son değerinden sonraki ilk ay
(TÜFE güncelse — bu ay zaten açıklanmışsa — son değer bu aydır, hedef doğal
olarak sonraki ay olur). Kesit ``asof_monthly(seri, cutoff=bugün)`` ile kurulur:
backtest motorunun kullandığı AYNI fonksiyon (Review Focus 1); ayrı/gevşek bir
kesit yolu açılmaz. Modeller motorun ModelFn sözleşmesiyle çağrılır; ModelFailure
VEYA ham exception (TSFM ağırlık yükleme hatası gibi) çökme değil normal iş
akışıdır — o model ``ok: false, error`` satırı olur, süreç exit 0 döner
(Faz 1 T14 kuralı + Review Focus 3: CI'da çöken model siteyi kırmaz).

Yıllık türetme (Review Focus 2): son 11 gerçek aylık % + hedef ay tahmini →
kümülatif çarpım ``((1+a1)·…·(1+a12) − 1)·100``; nokta ve bant uçlarına aynı
formül. Gerçek ay 11'den azsa veya başarılı tahmin yoksa ``yillik: null``
(uydurma yok). Çoklu modelde yıllık, başarılı tahminlerin medyanından türetilir.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from trnowcast.backtest import ModelFn, asof_monthly
from trnowcast.models import MODELS
from trnowcast.scoring import HEDEF_SERI
from trnowcast.store import load_series, registry

# Yıllık türetmede tahmine eklenen gerçek aylık % sayısı (11 + tahmin = 12 ay).
YILLIK_GERCEK_AY = 11

YILLIK_TEMEL_NOTU = "son 11 gerçek ay + hedef tahmini"


def _simdi() -> datetime:
    """Koşum anı; testler monkeypatch ile sabitler (şema + idempotentlik testleri)."""
    return datetime.now(UTC)


def _gun_zamani(an: datetime) -> str:
    """ISO gün damgası. Duvar saati saniyeli damga iki üst üste koşumu farklı
    bayt yapar (Review Focus 4'ün CI-gürültüsü amacı boşa düşer); aylık veri
    hattında gün hassasiyeti dürüst ve yeterlidir."""
    return an.date().isoformat()


def kesit_gunu() -> str:
    """Koşum anının kesit günü (ISO) — nowcast.json tazeliğini ölçmek için."""
    return _gun_zamani(_simdi())


def hedef_ayi() -> pd.Timestamp:
    """Hedef ay: hedef serideki son değerin ayından sonraki ilk ay."""
    seri = load_series(HEDEF_SERI)
    son = seri["date"].max().to_period("M")
    return (son + 1).start_time


def _kesit(cutoff: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Tüm registry için cutoff kesiti — run_backtest'in kurduğu yolun aynısı."""
    return {ad: asof_monthly(ad, cutoff) for ad in registry()}


def _kumulatif_yillik(aylik_yuzdeler: list[float]) -> float:
    """((1+a1)·…·(1+an) − 1)·100 — çarpımsal (kümülatif) yıllıklaştırma."""
    carpim = 1.0
    for a in aylik_yuzdeler:
        carpim *= 1.0 + float(a) / 100.0
    return (carpim - 1.0) * 100.0


def _yillik(gecmis: pd.Series, tahminler: list[dict]) -> dict | None:
    """Son 11 gerçek ay + başarılı tahminlerin medyanı → kümülatif yıllık; değilse None."""
    son11 = gecmis.dropna().tail(YILLIK_GERCEK_AY)
    basarili = [t for t in tahminler if t["ok"]]
    if len(son11) < YILLIK_GERCEK_AY or not basarili:
        return None
    taban = [float(x) for x in son11]
    medyan = {
        k: float(np.median([t[k] for t in basarili]))
        for k in ("point", "lower", "upper")
    }
    return {
        "point": _kumulatif_yillik(taban + [medyan["point"]]),
        "lower": _kumulatif_yillik(taban + [medyan["lower"]]),
        "upper": _kumulatif_yillik(taban + [medyan["upper"]]),
        "temel": YILLIK_TEMEL_NOTU,
    }


def nowcast_kos(models: dict[str, ModelFn] | None = None) -> dict:
    """Güncel ay için tek-koşum nowcast; JSON'a hazır sözlük döndürür.

    Şema: ``{"generated_at": ISO gün, "cutoff_date": ISO gün,
    "target_month": "YYYY-MM", "forecasts": [{"model", "point", "lower",
    "upper", "ok", "error"}], "yillik": {"point", "lower", "upper", "temel"}
    | None}``.
    models verilmezse tüm arena (MODELS — 8 yarışmacı) koşar. Model başına
    başarısızlık (ModelFailure VEYA ham exception — timesfm adapter'ı yükleme
    hatasını try DIŞINDA ham olarak fırlatır, tsfm_timesfm.py) normal iş
    akışıdır: o model ok:false, error satırı olur, fonksiyon çökmez.
    """
    if models is None:
        models = MODELS
    simdi = _simdi()
    # Kesit günü: depo tarihleri tz-naive olduğundan cutoff da naive gün olur.
    cutoff = pd.Timestamp(simdi.date())
    hedef = hedef_ayi()
    kesit = _kesit(cutoff)

    tahminler: list[dict] = []
    for ad, fn in models.items():
        try:
            fp = fn(kesit, hedef, HEDEF_SERI)
            tahminler.append(
                {
                    "model": ad,
                    "point": float(fp.point),
                    "lower": float(fp.lower),
                    "upper": float(fp.upper),
                    "ok": True,
                    "error": None,
                }
            )
        # Blind catch sözleşmenin kendisi: model başına ok:false — TSFM
        # kütüphanelerinin (torch/HF) herhangi bir hatası siteyi kırmaz;
        # hata mesajı satırda korunur, sessiz yutma yok (Review Focus 3).
        except Exception as hata:  # noqa: BLE001
            tahminler.append(
                {
                    "model": ad,
                    "point": None,
                    "lower": None,
                    "upper": None,
                    "ok": False,
                    "error": str(hata),
                }
            )

    tam = load_series(HEDEF_SERI)
    gecmis = tam.groupby(tam["date"].dt.to_period("M"))["value"].last()
    return {
        "generated_at": _gun_zamani(simdi),
        "cutoff_date": cutoff.strftime("%Y-%m-%d"),
        "target_month": f"{hedef:%Y-%m}",
        "forecasts": tahminler,
        "yillik": _yillik(gecmis, tahminler),
    }


def json_metni(payload) -> str:
    """Deterministik JSON metni (sabit alan sırası, girinti, sondaki satır sonu).

    allow_nan=False: NaN'lı değer sızarsa yazım yerine hata — sessiz bozuk JSON yok.
    """
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
