"""TCMB Piyasa Katılımcıları Anketi — TÜFE beklentisi, PKA "uygun ortalama".

Sorumluluk: tasarım dokümanındaki model arenasının 5. yarışmacısı; üretilen
aylık TÜFE tahminlerinin anket beklentisiyle kıyası. Veri EVDS üzerinden
çekilir (anahtar gerekir → trnowcast.sources.evds.EvdsClient kullanılır).

Kullanılan soru ve istatistik:
- soru: "Cari Ayın Aylık TÜFE Beklentisi (% Değişim)" — anketin ait olduğu ay
  için aylık TÜFE % değişim beklentisi; hedef değişkenle (aylık TÜFE % değişim)
  doğrudan karşılaştırılabilir.
- istatistik: UYGUN ORTALAMA — medyan DEĞİL. TCMB PKA raporları beklentileri
  "her değişken için hesaplanan uygun ortalama" olarak yayımlar (PKA Ekim 2026
  raporu s.5; dipnot: "Uygun ortalama değerleridir", s.6 — raporu denetçi
  indirip okudu, 2026-11-06). Seri adı bu yüzden tufe_beklenti_pka'dır: ad,
  döndürülen istatistiği dürüstçe anlatır. EVDS'te anket istatistikleri
  "Tanımsal İstatistikler" grubu (bie_urbek) altında soru-başına
  serileştirilmiştir; kod son eki istatistiği seçer: .M = Medyan,
  .U = Uygun Ortalama, .A = Aritmetik Ortalama, .S = Standart Sapma,
  .X = Gözlem Sayısı.
- seri kodu: TP.BEK.S01.A.U — 2026-11-06 canlı teyit (EVDS_API_KEY ile,
  2026-6..2026-10): .M (medyan) ve .U kanalları farklı değerler döndürür
  (.M = 1.40/1.70/1.70/2.05/2.20; .U = 1.36/1.68/1.67/2.12/2.11) ve .U'nun
  Ekim değeri (2.11), TCMB PKA Ekim 2026 raporundaki "Cari Ay" uygun
  ortalamasıyla (2,11) birebir uyuşur; .M uyuşmaz. Kanal geçmişi (dürüst
  kayıt): T10'un ilk yaması boru kodunu .M bırakıp adı/üstveriyi "uygun
  ortalama" yazmıştı — bu kanıtla çelişti; denetçi bulgusuyla kod .U'ya
  çevrildi.

Alternatifler (docstring kaydı):
- medyan kardeş seri: TP.BEK.S01.A.M (farklı değerler döndürür, kullanılmıyor)
- yıl sonu serisi: TP.BEK.S01.D.M (cari yıl sonu yıllık TÜFE beklentisi)
- bie_pkauo grubu alternatifi: TP.PKAUO.S01.A.U

Veri URL'i (erişim/teyit tarihi: 2026-11-05, .U kanalıyla yeniden teyit 2026-11-06):
- EVDS veri grubu: bie_urbek — "Piyasa Katılımcıları Anketi (TCMB) / Tanımsal
  İstatistikler", kategori 1004, https://evds3.tcmb.gov.tr/tumSeriler/1004/bie_urbek
- teyit yöntemi: 2026-11-06 canlı API çekimi (EVDS_API_KEY ile; 2026-6..2026-10
  penceresi döndü — tests/fixtures/evds_survey.json .U kanalının gerçek canlı
  kesittir). EVDS 3 aylık serilerde Tarih "YYYY-M" ve değerler nokta
  ondalıklıdır; ikisi de evds.parse_json'da desteklenir (T9 geçişiyle düzeltildi).

Yayın zamanı: anket sonuçları ait olduğu ay içinde (yaklaşık ayın 3. haftası)
açıklanır — yani değer ay bitmeden yayındadır; bu yüzden publication_lag_days
= 0 tutulur (negatif gecikme yerine taban değeri + bu not).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from trnowcast.sources import evds

SERIES_NAME = "tufe_beklenti_pka"
EVDS_CODE = "TP.BEK.S01.A.U"

# Piyasa Katılımcıları Anketi'nin güncel (bie_* aktif) serileri 2013-01'den itibaren.
FETCH_START = date(2013, 1, 1)


def fetch(api_key: str | None) -> pd.DataFrame:
    """Anket TÜFE beklentisini (uygun ortalama) long format çerçevesi olarak döndürür.

    date ay-başına normalize edilir (ortak şema: aylık seriler ay-başı);
    series_id, SERIES_NAME olur.
    """
    client = evds.EvdsClient(api_key)
    df = client.get(EVDS_CODE, FETCH_START, date.today())
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["series_id"] = SERIES_NAME
    return df


def fetch_all(api_key: str | None) -> list[Path]:
    """Seriyi çekip T2 deposuna yazar; parquet yolunu tek öğeli liste döndürür."""
    df = fetch(api_key)
    # fred.py ile aynı düzen: T2 paralel geliştirildiği için import çağrı anında.
    from trnowcast.store import SeriesMeta, save_series

    meta = SeriesMeta(
        name=SERIES_NAME,
        source="TCMB Piyasa Katılımcıları Anketi (EVDS bie_urbek)",
        url=evds.seri_url(EVDS_CODE, FETCH_START, date.today()),
        frequency="aylık",
        units="% (aylık TÜFE değişim beklentisi, uygun ortalama)",
        publication_lag_days=0,
        license_note=(
            "TCMB Piyasa Katılımcıları Anketi, Tanımsal İstatistikler (bie_urbek) "
            "grubunun uygun ortalama serisi (TP.BEK.S01.A.U); EVDS anahtarı "
            "(EVDS_API_KEY) gerekir. 2026-11-06 canlı teyit: medyan kardeş seri "
            "(TP.BEK.S01.A.M) farklı değerler döndürür ve kullanılmaz; .U değeri "
            "TCMB PKA raporunun uygun ortalamasıyla birebir uyuşur (Ekim 2026: 2.11)."
        ),
    )
    return [save_series(meta, df)]
