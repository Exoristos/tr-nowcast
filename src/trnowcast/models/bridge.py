"""Bridge / MIDAS-lite model (T17) — yorumlanabilir çok değişkenli.

Tasarım matrisi: hedef serinin 1/2/3-ay gecikmesi + her sürücünün 1-ay
gecikmesi (usd_try_gunluk, brent_gunluk, fao_gida_endeks; kesitte yoksa o
sütun atlanır) + sabit. ``Ridge(alpha=1.0)`` cutoff kesitinde fit edilir;
``fit_intercept=True`` sabit terimdir ve cezalandırılmaz. Nokta = hedef aya
tek adım öngörü; bant = eğitim artığının mutlak değerlerinin %80 persentili
(min 0.2 — Faz 1 naive kuralı gibi eğitim kesitinden kurulur). Eğitim satırı
< 36 → ModelFailure.

Sızıntı (Review Focus 4): katsayılar yalnız t <= kesit sonu satırlarından
öğrenilir; sürücünün hedef ay ve sonrasındaki değeri ne eğitimde ne tahmin
satırında okunur — test, gelecek değeri değişince tahminin değişmediğini
kanıtlar. ModelFn sözleşmesi (Faz 1) gereği model yalnız motor kesiti
sözlüğüne bakar; ham store erişimi imzada yok.

Gecikmeler pozisyonel ``shift`` ile değil ay (Period) hizasıyla kurulur:
kesitte ay boşluğu olsa bile t-1 ayının değeri doğru satıra düşer.

scikit-learn importu fonksiyon içinde lazy: CLI'ın diğer komutları sklearn
yüklemeden çalışır.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trnowcast.backtest import ForecastPoint, ModelFailure

MODEL_ADI = "bridge"
SURUCULER = ("usd_try_gunluk", "brent_gunluk", "fao_gida_endeks")
HEDEF_GECIKMELER = (1, 2, 3)
MIN_EGITIM_SATIRI = 36
BANT_MIN = 0.2
BANT_PERSANTIL = 80.0


def _ay_serisi(kesit: dict[str, pd.DataFrame], ad: str) -> pd.Series | None:
    """Seri df'ini PeriodIndex'li float Series'e çevirir; yoksa/boşsa None."""
    if ad not in kesit or kesit[ad].empty:
        return None
    s = kesit[ad]["value"].astype(float).dropna()
    if s.empty:
        return None
    return pd.Series(s.to_numpy(), index=s.index.to_period("M")).sort_index()


def _gecikme(s: pd.Series, k: int) -> pd.Series:
    # s(t-k) değerini t ayına yerleştirir; pozisyonel shift değil, ay hizası.
    return pd.Series(s.to_numpy(), index=s.index + k)


def BRIDGE(kesit: dict[str, pd.DataFrame], hedef_ay: pd.Timestamp, target: str) -> ForecastPoint:
    hedef_p = pd.Timestamp(hedef_ay).to_period("M")

    hedef_s = _ay_serisi(kesit, target)
    if hedef_s is None:
        raise ModelFailure(f"{MODEL_ADI}: hedef seri kesitte yok ({target})")
    adim = (hedef_p - hedef_s.index[-1]).n
    if adim != 1:
        # Tek adım sözleşmesi: hedef ay yayında ya da 2+ ay ilerideyse tahmin yok.
        raise ModelFailure(
            f"{MODEL_ADI}: tek adım öngörü gerekli; hedef ay kesitten {adim} ay uzakta "
            f"({hedef_ay:%Y-%m})"
        )

    # Sürücü sütunları: kesitte olan VE hedef-1 ayında değeri bulunanlar.
    # (hedef-1 değeri olmayan sürücünün sütunu atlanır — graceful.)
    onceki_ay = hedef_p - 1
    suruculer: dict[str, pd.Series] = {}
    for ad in SURUCULER:
        s = _ay_serisi(kesit, ad)
        if s is not None and onceki_ay in s.index:
            suruculer[ad] = s

    # Tahmin satırı önce kurulur: sürücü sütun kümesi bununla aynı olmalı.
    tahmin_satiri = {f"hedef_g{k}": hedef_s.get(hedef_p - k) for k in HEDEF_GECIKMELER}
    for k in HEDEF_GECIKMELER:
        if tahmin_satiri[f"hedef_g{k}"] is None or not np.isfinite(tahmin_satiri[f"hedef_g{k}"]):
            raise ModelFailure(f"{MODEL_ADI}: hedef gecikme değeri yok (t-{k}, {hedef_p - k})")
    for ad, s in suruculer.items():
        tahmin_satiri[f"surucu_{ad}"] = float(s.loc[onceki_ay])

    # Eğitim matrisi: satır ayı t, hedef(t) = f(hedef t-1/-2/-3, sürücü t-1, sabit).
    sutunlar: dict[str, pd.Series] = {f"hedef_g{k}": _gecikme(hedef_s, k) for k in HEDEF_GECIKMELER}
    for ad, s in suruculer.items():
        sutunlar[f"surucu_{ad}"] = _gecikme(s, 1).reindex(hedef_s.index)
    # Eğitim satırları yalnız hedefin gözlemlendiği aylar: gecikme sütunlarının
    # PeriodIndex birleşimi hedef ayın ötesine taşabilir — satır düşürmeden sınırla.
    X = pd.DataFrame(sutunlar).loc[: hedef_s.index[-1]].dropna()
    y = hedef_s.reindex(X.index)
    if len(X) < MIN_EGITIM_SATIRI:
        raise ModelFailure(f"{MODEL_ADI}: yetersiz eğitim satırı ({len(X)} < {MIN_EGITIM_SATIRI})")

    from sklearn.linear_model import Ridge

    try:
        model = Ridge(alpha=1.0)
        model.fit(X.to_numpy(), y.to_numpy())
        nokta = float(model.predict(pd.DataFrame([tahmin_satiri])[X.columns].to_numpy())[0])
    except ModelFailure:
        raise
    except Exception as hata:
        raise ModelFailure(f"{MODEL_ADI} başarısız: {hata}") from hata

    if not np.isfinite(nokta):
        raise ModelFailure(f"{MODEL_ADI}: tahmin NaN/inf")

    # Bant: eğitim artığı |hata| %80 persentili; 0.2 tabanıyla.
    kalinti = y.to_numpy() - model.predict(X.to_numpy())
    bant = max(float(np.percentile(np.abs(kalinti), BANT_PERSANTIL)), BANT_MIN)
    if not np.isfinite(bant):
        raise ModelFailure(f"{MODEL_ADI}: bant tanımsız")

    return ForecastPoint(
        target_month=pd.Timestamp(hedef_ay),
        point=nokta,
        lower=nokta - bant,
        upper=nokta + bant,
        model=MODEL_ADI,
    )
