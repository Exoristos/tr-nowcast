"""trnowcast komut satırı arayüzü (Faz 0 / T7).

Komutlar:
- fetch [--source all|fred|fao|tuik|evds]: kaynakları çekip T2 deposuna yazar.
  evds → evds + TCMB anketi (ikisi de EVDS_API_KEY ister); anahtar tanımsızsa
  bilgilendirilir ve bu kaynaklar atlanır — traceback yok (Review Focus 2).
  Kaynak hatasında (SourceError) o kaynak atlanır, diğerleri sürer; denenen
  TÜM kaynaklar başarısızsa exit 1 (anahtar-yok atlaması başarısızlık sayılmaz).
- status: registry tablosu; kırılan kaynaklar fetch_log.json'dan "kaynak durumu"
  bölümünde görünür (Review Focus 1: TÜİK şema kırılmasında iz).
- quality: tüm serilerde kalite kontrolleri; hard-fail varsa exit 1.
- backtest [--start YYYY-AA] [--end YYYY-AA] [--models classic|all|CSV]:
  as-of backtest; skorlar parquet'e yazılır; ModelFailure normal iş akışı
  (exit 0). TSFM'ler (chronos2_uni, timesfm3_mv) GPU ister — CI'da koşmaz.
- nowcast [--models ...] [--out YOL] ve export [--out DIZIN]: canlı tahmin ve
  site veri ihracı (T20) — tanımları cli_canli.py'de (250 satır kuralı).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import click

from trnowcast import store
from trnowcast.cli_canli import export_cmd, nowcast_cmd
from trnowcast.models import modeller_sec
from trnowcast.quality import CheckResult, check_series
from trnowcast.scoring import backtest_kos, skor_yolu, tablo_satirlari
from trnowcast.sources import SourceError, evds, fao, fred, survey, tuik


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """TR-Nowcast veri hattı: açık kaynaklardan Türkiye enflasyon verisi çeker,
    kalite kontrol eder ve her serinin yayın takvimini registry'de tutar."""
    # argümansız çağrı: komut listesini bas ve exit 0 (click'in varsayılanı exit 2)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


main.add_command(nowcast_cmd)
main.add_command(export_cmd)


def _fetch_hedefleri(kaynak: str) -> list[tuple[str, Callable[[], list[Path]]]]:
    """--source seçimine göre çekilecek (etiket, fetch_all) çiftlerini kurar."""
    hedefler: list[tuple[str, Callable[[], list[Path]]]] = []
    if kaynak in ("all", "fred"):
        hedefler.append(("fred", fred.fetch_all))
    if kaynak in ("all", "fao"):
        hedefler.append(("fao", fao.fetch_all))
    if kaynak in ("all", "tuik"):
        hedefler.append(("tuik", tuik.fetch_all))
    if kaynak in ("all", "evds"):
        anahtar = os.environ.get("EVDS_API_KEY")
        if anahtar:
            hedefler.append(("evds", lambda: evds.fetch_all(anahtar)))
            hedefler.append(("anket", lambda: survey.fetch_all(anahtar)))
        else:
            click.echo(
                "EVDS_API_KEY tanımsız — evds ve TCMB anket kaynakları atlandı "
                "(ücretsiz anahtar: https://evds3.tcmb.gov.tr)"
            )
            for ad in ("evds", "anket"):
                _durum_yaz(ad, "atlandı", "EVDS_API_KEY tanımsız")
    return hedefler


@main.command()
@click.option(
    "--source",
    "kaynak",
    type=click.Choice(["all", "fred", "fao", "tuik", "evds"]),
    default="all",
    show_default=True,
    help="Çekilecek kaynak; evds seçimi evds + TCMB anketini kapsar.",
)
def fetch(kaynak: str) -> None:
    """Kaynakları çekip depoya (parquet + registry) yazar."""
    basarili: list[str] = []
    basarisiz: list[str] = []
    for ad, cek in _fetch_hedefleri(kaynak):
        try:
            yollar = cek()
        except SourceError as hata:
            basarisiz.append(ad)
            click.echo(f"[HATA] {ad}: {hata}")
            _durum_yaz(ad, "hata", str(hata))
        else:
            basarili.append(ad)
            click.echo(f"[OK] {ad}: {len(yollar)} seri kaydedildi")
            _durum_yaz(ad, "ok", f"{len(yollar)} seri kaydedildi")
    if basarisiz and not basarili:
        click.echo("Tüm kaynaklar başarısız oldu — hiçbir seri güncellenmedi.")
        sys.exit(1)


def _durum_yolu() -> Path:
    return store.DATA_ROOT / "processed" / "fetch_log.json"


def _durum_oku() -> dict:
    yol = _durum_yolu()
    if not yol.exists():
        return {}
    return json.loads(yol.read_text(encoding="utf-8"))


def _durum_yaz(ad: str, durum: str, mesaj: str) -> None:
    """Kaynak çekim sonucunu (ok/hata/atlandı) kalıcı kayda yazar.

    Registry yalnız başarılı save_series'de güncellendiği için kırılan kaynağın
    izi yalnız burada yaşar; atomik yazım (tmp + os.replace) T2 düzeniyle aynı.
    """
    kayit = _durum_oku()
    kayit[ad] = {
        "durum": durum,
        "mesaj": mesaj,
        "zaman": datetime.now(UTC).isoformat(),
    }
    yol = _durum_yolu()
    yol.parent.mkdir(parents=True, exist_ok=True)
    tmp = yol.with_name(yol.name + ".tmp")
    tmp.write_text(
        json.dumps(kayit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, yol)


def _kaynak_durumu() -> None:
    """Son fetch denemelerinin kalıcı kaydını gösterir; hiç kayıt yoksa sessiz."""
    durum = _durum_oku()
    if not durum:
        return
    etiketler = {"ok": "OK", "hata": "HATA", "atlandı": "ATLANDI"}
    click.echo("")
    click.echo("kaynak durumu (son fetch):")
    for ad in sorted(durum):
        girdi = durum[ad]
        etiket = etiketler.get(girdi["durum"], girdi["durum"].upper())
        click.echo(f"  [{etiket}] {ad}: {girdi['mesaj']} ({girdi['zaman'][:19]})")


def _hizali(satirlar: list[tuple[str, ...]]) -> list[str]:
    """Sütunları en geniş hücreye göre hizalar; başlık dahil tüm satırlar için."""
    genislikler = [max(len(satir[i]) for satir in satirlar) for i in range(len(satirlar[0]))]
    return [
        "  ".join(hucre.ljust(genislikler[i]) for i, hucre in enumerate(satir)).rstrip()
        for satir in satirlar
    ]


def _evds_anahtar_notu(kayit: dict) -> None:
    """EVDS ailesi serileri eksikse ve anahtar tanımsızsa bilgilendirir
    (Review Focus 2: 'anahtar yok' durumu status'ta görünür olmalı)."""
    beklenen = set(evds.SERIES) | {survey.SERIES_NAME}
    eksik = sorted(beklenen - set(kayit))
    if eksik and not os.environ.get("EVDS_API_KEY"):
        click.echo(
            "not: EVDS kaynakları kayıtlı değil (" + ", ".join(eksik) + ") — "
            "EVDS_API_KEY tanımsız; anahtarla 'trnowcast fetch --source evds' çalıştırın"
        )


@main.command()
def status() -> None:
    """Registry'deki serileri tablo olarak gösterir; son fetch sonuçlarını da raporlar."""
    kayit = store.registry()
    if not kayit:
        click.echo("Registry boş — önce 'trnowcast fetch' çalıştırın.")
    else:
        satirlar: list[tuple[str, ...]] = [
            ("seri", "kaynak", "son değer", "satır", "son fetch")
        ]
        for ad in sorted(kayit):
            girdi = kayit[ad]
            try:
                df = store.load_series(ad)
                son_deger = f"{df['date'].max():%Y-%m-%d}" if not df.empty else "boş"
                satir_sayisi = str(len(df))
            except KeyError:
                son_deger = "PARQUET YOK"
                satir_sayisi = "-"
            satirlar.append(
                (ad, girdi["source"], son_deger, satir_sayisi, girdi["last_fetched"][:19])
            )
        for satir in _hizali(satirlar):
            click.echo(satir)
        _evds_anahtar_notu(kayit)
    _kaynak_durumu()


def _etiket(sonuc: CheckResult) -> str:
    if not sonuc.passed:
        return "HATA"
    return "UYARI" if sonuc.detail.startswith("UYARI:") else "OK"


@main.command()
def quality() -> None:
    """Tüm kayıtlı serilerde kalite kontrollerini çalıştırır; hard-fail varsa exit 1."""
    kayit = store.registry()
    if not kayit:
        click.echo("Registry boş — kontrol edilecek seri yok.")
        return
    hata_var = False
    for ad in sorted(kayit):
        click.echo(f"{ad}:")
        try:
            sonuclar = check_series(ad)
        except KeyError as hata:
            hata_var = True
            click.echo(f"  [HATA] {hata}")
            continue
        for sonuc in sonuclar:
            hata_var = hata_var or not sonuc.passed
            click.echo(f"  [{_etiket(sonuc)}] {sonuc.check}: {sonuc.detail}")
    if hata_var:
        click.echo("Kalite kontrolü başarısız — yukarıdaki [HATA] satırlarına bakın.")
        sys.exit(1)


@main.command()
@click.option("--start", "baslangic", default=None, metavar="YYYY-AA",
              help="Backtest başlangıç ayı; varsayılan 2019-01 (SCORE_START).")
@click.option("--end", "bitis", default=None, metavar="YYYY-AA",
              help="Backtest bitiş ayı; varsayılan serideki son aylık değerin ayı.")
@click.option("--models", "modeller", default="all", show_default=True,
              metavar="classic | all | CSV",
              help="Arenadan seçim: 'classic' (Faz 1 dörtlüsü), 'all' (8 yarışmacı), CSV.")
def backtest(baslangic: str | None, bitis: str | None, modeller: str) -> None:
    """Seçilen modellerle backtest koşar; skorları parquet'e yazar, özet tabloyu basar."""
    try:
        models = modeller_sec(modeller)
    except ValueError as hata:
        raise click.BadParameter(str(hata)) from hata
    sonuclar, tablo = backtest_kos(baslangic, bitis, models=models)
    click.echo(f"{len(sonuclar)} tahmin; pencere özeti:")
    for satir in _hizali(tablo_satirlari(tablo)):
        click.echo(satir)
    click.echo(f"skorlar: {skor_yolu()}")
