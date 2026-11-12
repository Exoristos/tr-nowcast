"""T7 kalite kontrolü testleri — tamamen offline, depo tmp_path'e yönlendirilir.

Bozuk depo durumları (sıra ihlali, mükerrer satır) save_series'in sıralama ve
tekilleştirme sözleşmesini atlayarak parquet'in elle üzerine yazılmasıyla
kurulur; registry girdileri gerçek SeriesMeta'dan üretilir.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trnowcast import store
from trnowcast.quality import check_series

SERI = "kalite_test_seri"


@pytest.fixture(autouse=True)
def _tmp_depo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_ROOT", tmp_path)


def _meta(name: str = SERI, **ek) -> store.SeriesMeta:
    return store.SeriesMeta(
        name=name,
        source="TestKaynak",
        url="https://ornek.test/veri.csv",
        frequency="aylık",
        units="test birimi",
        publication_lag_days=1,
        license_note="test kapsamı",
        **ek,
    )


def _df(values, baslangic="2025-01-01", seri: str = SERI) -> pd.DataFrame:
    tarihler = pd.date_range(baslangic, periods=len(values), freq="MS")
    degerler = [float(v) if v is not None else float("nan") for v in values]
    return pd.DataFrame(
        {"date": tarihler, "value": degerler, "series_id": seri}
    )


def _kaydet(values, name: str = SERI, **meta_ek) -> None:
    store.save_series(_meta(name, **meta_ek), _df(values, seri=name))


def _bozuk_parquet(name: str, df: pd.DataFrame) -> None:
    """Depo sözleşmesini (sıralama + tekilleştirme) atlayıp parquet'i değiştirir."""
    yol = store.DATA_ROOT / "processed" / f"{name}.parquet"
    df.to_parquet(yol, index=False)


def _bul(sonuclar, kontrol: str):
    eslesen = [r for r in sonuclar if r.check == kontrol]
    assert eslesen, f"'{kontrol}' yok — üretilen kontroller: {[r.check for r in sonuclar]}"
    return eslesen[0]


def test_sirali_saglam_seri_butun_kontrolleri_gecer():
    _kaydet([10.0, 11.0, 12.0])
    sonuclar = check_series(SERI)
    assert sonuclar, "en az bir kontrol üretilmeli"
    assert all(r.passed for r in sonuclar), sonuclar


def test_sirasi_bozuk_seri_hata_verir():
    _kaydet([1.0, 2.0, 3.0])
    ters = _df([1.0, 2.0, 3.0]).sort_values("date", ascending=False).reset_index(drop=True)
    _bozuk_parquet(SERI, ters)
    sonuc = _bul(check_series(SERI), "tarih sırası")
    assert not sonuc.passed
    assert "satır" in sonuc.detail


def test_mukerrer_satir_hata_verir():
    _kaydet([1.0, 2.0])
    # aynı (series_id, date) ikinci kez, revize değerle — idempotentlik ihlali
    tekrar = pd.concat(
        [_df([1.0, 2.0]), _df([9.9], baslangic="2025-01-01")], ignore_index=True
    )
    _bozuk_parquet(SERI, tekrar)
    sonuc = _bul(check_series(SERI), "tekilleştirme")
    assert not sonuc.passed
    assert "2025-01-01" in sonuc.detail


def test_nan_orani_esik_ustunde_hata():
    # 4 gözlemde 1 NaN = %25 > varsayılan eşik 0.05 (registry'den gelir)
    _kaydet([1.0, None, 3.0, 4.0])
    sonuc = _bul(check_series(SERI), "nan oranı")
    assert not sonuc.passed


def test_nan_orani_esik_altinda_gecer():
    # aynı veri, daha cömert eşik → geçer; eşiğin kaynağı meta'dır
    _kaydet([1.0, None, 3.0, 4.0], nan_threshold=0.3)
    sonuc = _bul(check_series(SERI), "nan oranı")
    assert sonuc.passed


def test_aralik_disi_deger_uyaridir_hard_fail_degil():
    # plan T7: aralık kontrolü uyarı düzeyidir; passed=True kalır
    _kaydet([8.0, 25.0], name="turkiye_tufe_aylik_yuzde", warn_range=(-2.0, 20.0))
    sonuc = _bul(check_series("turkiye_tufe_aylik_yuzde"), "değer aralığı")
    assert sonuc.passed
    assert sonuc.detail.startswith("UYARI:")
    assert "1 gözlem" in sonuc.detail
    assert "25" in sonuc.detail


def test_tufe_aylik_2021_2022_tarzi_zirveler_uyari_bile_uretmez():
    # Review Focus 5: aylık ~%5-13 zirveler [-2, 20] uyarı aralığında kalır
    _kaydet([5.0, 8.5, 13.0], name="turkiye_tufe_aylik_yuzde", warn_range=(-2.0, 20.0))
    sonuc = _bul(check_series("turkiye_tufe_aylik_yuzde"), "değer aralığı")
    assert sonuc.passed
    assert not sonuc.detail.startswith("UYARI:")


def test_aralik_esigi_metadan_degistirilebilir():
    # denetçi bulgusu: eşik quality'deki kod tablosundan değil, serinin
    # meta'sından (registry girdisi) gelir — meta'yı değiştirmek davranışı değiştirir
    _kaydet([8.0, 25.0], name="dar_aralikli", warn_range=(0.0, 5.0))
    dar = _bul(check_series("dar_aralikli"), "değer aralığı")
    assert dar.passed and dar.detail.startswith("UYARI:")
    assert "2 gözlem" in dar.detail

    _kaydet([8.0, 25.0], name="genis_aralikli", warn_range=(0.0, 30.0))
    genis = _bul(check_series("genis_aralikli"), "değer aralığı")
    assert genis.passed and not genis.detail.startswith("UYARI:")


def test_tuik_serisi_araligini_metadan_alir_kod_tablosundan_degil():
    # denetçi bulgusu: 'turkiye_tufe_aylik_yuzde_tuik' quality'deki seri adı
    # tablosunda yok — meta'da aralık yoksa kontrol atlanır, meta'da varsa uyarır
    _kaydet([25.0], name="turkiye_tufe_aylik_yuzde_tuik")
    atlanan = _bul(check_series("turkiye_tufe_aylik_yuzde_tuik"), "değer aralığı")
    assert atlanan.passed and "tanımlı değil" in atlanan.detail

    _kaydet([25.0], name="turkiye_tufe_aylik_yuzde_tuik", warn_range=(-2.0, 20.0))
    uyarili = _bul(check_series("turkiye_tufe_aylik_yuzde_tuik"), "değer aralığı")
    assert uyarili.passed and uyarili.detail.startswith("UYARI:")


def test_araligi_meta_tanimli_olmayan_seri_kontrolu_atlanir():
    _kaydet([70.0], name="brent_gunluk")
    sonuc = _bul(check_series("brent_gunluk"), "değer aralığı")
    assert sonuc.passed
    assert "tanımlı değil" in sonuc.detail


def test_bos_seri_hata_verir():
    bos = pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "value": pd.Series([], dtype="float64"),
            "series_id": pd.Series([], dtype="object"),
        }
    )
    store.save_series(_meta(), bos)
    sonuclar = check_series(SERI)
    assert not all(r.passed for r in sonuclar)
    assert any(r.check == "seri boş" for r in sonuclar)


def test_registryde_olmayan_seri_keyerror():
    with pytest.raises(KeyError):
        check_series("olmayan_seri")
