# T27 Playwright kanıt koşumu — canlı workers.dev önizlemesinden ekran görüntüsü
# + konsol 0 hata + gerçek sayı kontrolleri. Beklenen değerler repo'daki
# site/assets_root JSON'larından, sayfanın bicim.js kurallarıyla hesaplanır.
# Kullanım:
#   python3 site/kanit.py [URL]
# Varsayılan URL deploy çıktısındaki workers.dev adresidir. Çıktı stdout'a
# basılır; kanıt kaydı için docs/kanit/kanit-log.txt'e tee ile yazılır.
# Gereksinim: pip install playwright && playwright install chromium
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://tr-nowcast-site.enis-erdogan10.workers.dev"
KOK = Path(__file__).resolve().parent / "assets_root"
KANIT = KOK.parent.parent / "docs" / "kanit"
KANIT.mkdir(parents=True, exist_ok=True)

MASAUSTU_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
MOBIL_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def medyan(sirali):
    s = sorted(sirali)
    orta = len(s) // 2
    return s[orta] if len(s) % 2 == 1 else (s[orta - 1] + s[orta]) / 2


def sayi(n, hane=2, tr=True):
    return f"{n:.{hane}f}".replace(".", "," if tr else ".")


def yuzde(n, hane=2, tr=True):
    return f"%{sayi(n, hane, tr)}" if tr else f"{sayi(n, hane, tr)}%"


nowcast = json.loads((KOK / "nowcast.json").read_text())
scores = json.loads((KOK / "scores.json").read_text())
puanlar = [f["point"] for f in nowcast["forecasts"] if f["ok"] and f["point"] is not None]
orta = medyan(puanlar)
yillik = nowcast["yillik"]
anket = next(s for s in scores["scores"] if s["model"] == "anket_pka" and s["window"] == "2019→bugün")


def kontrol_et(sayfa, tr=True, beklenen_url=""):
    hatalar = []
    sayfa.on("pageerror", lambda e: hatalar.append(f"pageerror: {e}"))
    sayfa.on(
        "console",
        lambda m: hatalar.append(f"console.{m.type}: {m.text}") if m.type == "error" else None,
    )
    sayfa.wait_for_load_state("networkidle")
    sayfa.wait_for_timeout(1500)

    bant = sayfa.locator("#veri-hatasi")
    hero = sayfa.locator('[data-alan="nowcast-deger"]').inner_text().strip()
    yil = sayfa.locator('[data-alan="yillik-deger"]').inner_text().strip()
    anket_hucre = sayfa.locator('tr[data-model="anket_pka"] [data-alan="mae-all"]').inner_text().strip()
    spark = sayfa.locator('[data-alan="tufe_aylik-spark"]').get_attribute("points") or ""
    grafik = sayfa.locator("#tahmin-grafik").inner_html()
    return [
        ("konsol_hatasi", hatalar, 0, len(hatalar) == 0),
        ("veri_hatasi_bandi", bant.is_visible(), False, not bant.is_visible()),
        ("hero", hero, yuzde(orta, 2, tr), hero == yuzde(orta, 2, tr)),
        ("yillik", yil, f"~{yuzde(yillik['point'], 1, tr)}", yil == f"~{yuzde(yillik['point'], 1, tr)}"),
        ("anket_mae", anket_hucre, sayi(anket["mae"], 2, tr), anket_hucre == sayi(anket["mae"], 2, tr)),
        ("spark_nokta", len(spark.split()), ">0", len(spark.strip()) > 0),
        ("grafik_polyline", len(re.findall(r"<polyline", grafik)), ">=2", len(re.findall(r"<polyline", grafik)) >= 2),
        ("son_url", sayfa.url, beklenen_url, sayfa.url == beklenen_url),
    ]


tum_iyi = True
print(f"kanit URL: {URL}")
with sync_playwright() as p:
    tarayici = p.chromium.launch()

    kosumlar = [
        ("TR masaustu (1440x900)", MASAUSTU_UA, {"width": 1440, "height": 900}, "/", "tr-masaustu-1440.png", True),
        ("EN masaustu (1440x900)", MASAUSTU_UA, {"width": 1440, "height": 900}, "/en/", "en-masaustu-1440.png", False),
        ("Mobil (390x844, / -> /m/ 302)", MOBIL_UA, {"width": 390, "height": 844}, "/", "mobil-390x844.png", False),
    ]
    for ad, ua, vp, yol, png, tr in kosumlar:
        secenekler = {"viewport": vp, "user_agent": ua}
        if "390" in str(vp["width"]):
            secenekler |= {"is_mobile": True, "device_scale_factor": 2}
        baglam = tarayici.new_context(**secenekler)
        sayfa = baglam.new_page()
        sayfa.goto(URL + yol, wait_until="domcontentloaded")
        for anahtar, gercek, beklenen, iyi in kontrol_et(sayfa, tr=tr, beklenen_url=URL + ("/m/" if "390" in str(vp["width"]) else yol)):
            print(f"{ad} | {anahtar}: {gercek!r} (beklenen: {beklenen!r}) -> {'OK' if iyi else 'HATA'}")
            tum_iyi = tum_iyi and iyi
        sayfa.screenshot(path=str(KANIT / png), full_page=True)
        print(f"{ad} | ekran goruntusu: docs/kanit/{png}")
        baglam.close()
    tarayici.close()

print("SONUC:", "TUM KONTROLLER OK" if tum_iyi else "HATA VAR")
raise SystemExit(0 if tum_iyi else 1)
