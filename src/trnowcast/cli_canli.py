"""Canlı nowcast ve site ihracı komutları (T20) — cli.py'den ayrık (250 satır kuralı).

cli.py bu modülün komutlarını ``main.add_command`` ile gruba bağlar; burada
click grubu tanımlanmaz, döngüsel içe aktarım olmaz.
"""

from __future__ import annotations

from pathlib import Path

import click

from trnowcast import store
from trnowcast.export import export_site
from trnowcast.models import modeller_sec
from trnowcast.nowcast import json_metni, nowcast_kos


@click.command("nowcast")
@click.option(
    "--models",
    "modeller",
    default="all",
    show_default=True,
    metavar="classic | all | CSV",
    help="Arenadan seçim; backtest --models ile aynı kurallar.",
)
@click.option(
    "--out",
    "cikti",
    default=None,
    metavar="YOL",
    help="JSON çıktı yolu; varsayılan data/processed/nowcast.json.",
)
def nowcast_cmd(modeller: str, cikti: str | None) -> None:
    """Güncel ay için modellerin canlı tahminini üretir; ModelFailure normal iş akışı (exit 0)."""
    try:
        models = modeller_sec(modeller)
    except ValueError as hata:
        raise click.BadParameter(str(hata)) from hata
    sonuc = nowcast_kos(models)
    # Depo kökü çağrı anında okunur; testler DATA_ROOT'u monkeypatch edebilir.
    yol = Path(cikti) if cikti else store.DATA_ROOT / "processed" / "nowcast.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json_metni(sonuc), encoding="utf-8")
    click.echo(f"hedef ay: {sonuc['target_month']}  kesit: {sonuc['cutoff_date']}")
    for t in sonuc["forecasts"]:
        if t["ok"]:
            click.echo(
                f"  [OK]  {t['model']:<14} {t['point']:+.2f} "
                f"({t['lower']:+.2f} … {t['upper']:+.2f})"
            )
        else:
            click.echo(f"  [YOK] {t['model']:<14} {t['error']}")
    yillik = sonuc["yillik"]
    if yillik:
        click.echo(
            f"türetilmiş yıllık: {yillik['point']:+.2f} "
            f"({yillik['lower']:+.2f} … {yillik['upper']:+.2f})"
        )
    click.echo(f"çıktı: {yol}")


@click.command("export")
@click.option(
    "--out",
    "cikti",
    default=None,
    metavar="DIZIN",
    help="Çıktı dizini; varsayılan data/site.",
)
@click.option(
    "--assets-root",
    "assets_root",
    default=None,
    metavar="DIZIN",
    help="Verilirse yazılan dosyalar aynı göreli yapıyla buraya da kopyalanır "
    "(ör. site/assets_root — Worker asset kökü). Varsayılan kapalı.",
)
def export_cmd(cikti: str | None, assets_root: str | None) -> None:
    """Site veri setini (nowcast, scores, chart, seriler, meta) JSON olarak yazar."""
    yollar = export_site(
        Path(cikti) if cikti else None,
        Path(assets_root) if assets_root else None,
    )
    for y in yollar:
        click.echo(f"[OK] {y}")
