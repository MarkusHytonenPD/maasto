"""
Regressiotesti pipeline.py:n erissä-ajolle — monta GPX:ää, aukkosuojaus ja
duplikaattikirjanpito. Käyttää oikeita GPX- ja JPEG-tiedostoja (piexif-EXIF),
mutta ei koske projekteihin, repoon eikä gitiin: kaikki tapahtuu väliaikais-
hakemistossa. Vaatii samat kirjastot kuin pipeline.py.

Ajo:
    python3 test_pipeline.py

Palauttaa 0 jos kaikki väittämät menevät läpi, muuten 1 (ja jättää
väliaikaishakemiston paikalleen tutkimista varten).
"""
import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import piexif
import geopandas as gpd
from PIL import Image
from shapely.geometry import Point

import pipeline as P

BASE = Path(tempfile.mkdtemp(prefix="pipeline-testi-"))
SRC1, SRC2, PROJ = BASE / "era1", BASE / "era2", BASE / "projekti"
for d in (SRC1, SRC2, PROJ):
    d.mkdir(parents=True)
print(f"Väliaikaishakemisto: {BASE}")

P.KUVA_POLKU = PROJ / "kuvat"
P.DATA_POLKU = PROJ / "data"
P.GITHUB_BASE_URL = "https://example.invalid/kuvat/"

virheet = []
def tarkista(ehto, viesti):
    print(("  OK   " if ehto else "  FAIL ") + viesti)
    if not ehto:
        virheet.append(viesti)


# ── GPX-apuri: UTC-ajat Z-suffiksilla kuten BasicAirData GPS Logger ──────────
def kirjoita_gpx(polku, alku_utc, minuutteja, lat0, lon0):
    pts = []
    for i in range(minuutteja + 1):
        t = alku_utc + datetime.timedelta(minutes=i)
        pts.append(
            f'<trkpt lat="{lat0 + i*0.0001:.6f}" lon="{lon0 + i*0.0001:.6f}">'
            f'<time>{t.strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>'
        )
    polku.write_text(
        '<?xml version="1.0"?><gpx version="1.1" creator="test"><trk><trkseg>'
        + "".join(pts)
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )


def tee_jpg(polku, dt, make="samsung", gps=None):
    img = Image.new("RGB", (32, 32), (120, 140, 160))
    def rat(v):
        v = abs(v); d = int(v); m = int((v - d) * 60)
        s = round((v - d - m / 60) * 3600 * 10000)
        return ((d, 1), (m, 1), (s, 10000))
    gps_ifd = {}
    if gps:
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: rat(gps[0]),
            piexif.GPSIFD.GPSLongitudeRef: b"E", piexif.GPSIFD.GPSLongitude: rat(gps[1]),
        }
    exif = piexif.dump({
        "0th": {piexif.ImageIFD.Make: make.encode()},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: dt.strftime("%Y:%m:%d %H:%M:%S").encode()},
        "GPS": gps_ifd, "1st": {}, "thumbnail": None,
    })
    img.save(polku, exif=exif)


# ══════════════════════════════════════════════════════════════════
print("\n[1] Monta GPX:ää yhdistyy, päällekkäiset karsitaan")
# Päivä 1 klo 12:00–12:10 UTC (= 15:00–15:10 Helsinki, kesäaika)
kirjoita_gpx(BASE / "paiva1.gpx", datetime.datetime(2026, 7, 20, 12, 0), 10, 62.43, 26.06)
# Päivä 2 klo 06:00–06:10 UTC (= 09:00–09:10 Helsinki) — yön mittainen aukko välissä
kirjoita_gpx(BASE / "paiva2.gpx", datetime.datetime(2026, 7, 21, 6, 0), 10, 62.44, 26.07)
shutil.copy(BASE / "paiva1.gpx", BASE / "paiva1_kopio.gpx")

pisteet = P._lataa_gpx_pisteet([BASE / "paiva1.gpx", BASE / "paiva2.gpx", BASE / "paiva1_kopio.gpx"])
tarkista(len(pisteet) == 22, f"22 uniikkia pistettä kolmesta lokista (sai {len(pisteet)})")
tarkista(pisteet == sorted(pisteet, key=lambda p: p[0]), "pisteet aikajärjestyksessä")
tarkista(pisteet[0][0] == datetime.datetime(2026, 7, 20, 15, 0), f"UTC→Helsinki: {pisteet[0][0]}")
tarkista(P._lataa_gpx_pisteet(BASE / "paiva1.gpx") != [], "yksi polku kelpaa yhä sellaisenaan")

print("\n[2] Aukon yli ei interpoloida")
aukot = P._aukot(pisteet, 10 * 60)
tarkista(len(aukot) == 1 and abs(aukot[0][2] - 1070) < 1,
         f"yksi aukko havaittu, {aukot[0][2]:.0f} min (15:10 → 09:00)")

# Kuva otettu yön aikana, aukon sisällä → ennen korjausta olisi saanut keksityn sijainnin
yolla = datetime.datetime(2026, 7, 21, 2, 0)
koord, syy = P._interpoloi(pisteet, yolla, 10 * 60)
tarkista(koord is None and "aukko" in syy.lower(), f"yöllä otettu kuva ohitetaan: {syy}")

# Sama ilman aukkorajaa (vanha käytös) tuottaisi sijainnin
koord_vanha, _ = P._interpoloi(pisteet, yolla, 10**9)
tarkista(koord_vanha is not None, "ilman rajaa vanha logiikka olisi interpoloinut (vertailu)")

# Radan sisällä oleva kuva saa yhä sijaintinsa
koord, syy = P._interpoloi(pisteet, datetime.datetime(2026, 7, 20, 15, 5, 30), 10 * 60)
tarkista(koord is not None and abs(koord[0] - 62.43055) < 0.0002, f"radalla oleva kuva: {koord} {syy}")

# Kokonaan lokien ulkopuolella
koord, syy = P._interpoloi(pisteet, datetime.datetime(2026, 7, 19, 8, 0), 10 * 60)
tarkista(koord is None and "ulkopuolella" in syy, f"lokien ulkopuolella: {syy}")

print("\n[3] Geotägäys kahdesta lokista yhdellä ajolla")
tee_jpg(SRC1 / "DSC_0001.JPG", datetime.datetime(2026, 7, 20, 15, 5), make="NIKON CORPORATION")
tee_jpg(SRC1 / "DSC_0002.JPG", datetime.datetime(2026, 7, 21, 9, 5), make="NIKON CORPORATION")
tee_jpg(SRC1 / "DSC_0003.JPG", datetime.datetime(2026, 7, 21, 2, 0), make="NIKON CORPORATION")  # yöllä
P.geotaggeri(SRC1, [BASE / "paiva1.gpx", BASE / "paiva2.gpx"], 0, 10)
tarkista(P.lue_exif_gps(SRC1 / "DSC_0001.JPG") is not None, "päivän 1 kuva geotägätty")
tarkista(P.lue_exif_gps(SRC1 / "DSC_0002.JPG") is not None, "päivän 2 kuva geotägätty samalla ajolla")
tarkista(P.lue_exif_gps(SRC1 / "DSC_0003.JPG") is None, "yöllinen kuva jäi ilman keksittyä sijaintia")

print("\n[4] Kuva-avain kestää geotägäyksen (koko muuttuu, avain ei)")
koko_ennen = (SRC1 / "DSC_0002.JPG").stat().st_size
avain = P._kuva_avain(SRC1 / "DSC_0002.JPG")
P.kirjoita_exif_gps(SRC1 / "DSC_0002.JPG", 62.44, 26.07)
tarkista(P._kuva_avain(SRC1 / "DSC_0002.JPG") == avain,
         f"avain sama EXIF-kirjoituksen jälkeen (koko {koko_ennen}→{(SRC1/'DSC_0002.JPG').stat().st_size})")

print("\n[5] Kuvia erissä: toinen ajo ei duplikoi")
lat_a, lon_a = 62.4305, 26.0605
lat_b, lon_b = 62.4400, 26.0700
x_a, y_a = P._wgs84_etrs(lat_a, lon_a)
x_b, y_b = P._wgs84_etrs(lat_b, lon_b)
gdf = gpd.GeoDataFrame({"tunnus": ["15", "17"]},
                       geometry=[Point(x_a, y_a), Point(x_b, y_b)], crs="EPSG:3067")
et = {"puhelin": 60, "drone": 300, "jarjestelmakamera": 300}

era1 = BASE / "kuvaera1"; era1.mkdir()
tee_jpg(era1 / "IMG_100.jpg", datetime.datetime(2026, 7, 20, 15, 2), gps=(lat_a, lon_a))
tee_jpg(era1 / "IMG_101.jpg", datetime.datetime(2026, 7, 20, 15, 3), gps=(lat_b, lon_b))

t1 = P.nimeä_kuvat(era1, gdf, et)
tarkista(t1["ok"] == 2 and t1["duplikaatti"] == 0, f"1. erä: {t1}")

t2 = P.nimeä_kuvat(era1, gdf, et)   # sama kansio uudelleen (vahinko)
tarkista(t2["ok"] == 0 and t2["duplikaatti"] == 2, f"2. ajo samalla kansiolla ei kopioi: {t2}")
tarkista(len(list(P.KUVA_POLKU.glob('*.jpg'))) == 2, "kuvia yhä 2 kpl kuvat-kansiossa")

print("\n[6] Uusi erä jatkaa numerointia, vanhat säilyvät")
era2 = BASE / "kuvaera2"; era2.mkdir()
tee_jpg(era2 / "IMG_200.jpg", datetime.datetime(2026, 7, 21, 9, 2), gps=(lat_a, lon_a))
shutil.copy(era1 / "IMG_100.jpg", era2 / "IMG_100.jpg")   # vahingossa mukaan jäänyt vanha
t3 = P.nimeä_kuvat(era2, gdf, et)
tarkista(t3["ok"] == 1 and t3["duplikaatti"] == 1, f"3. ajo: uusi kuva sisään, vanha ohi: {t3}")
tarkista((P.KUVA_POLKU / "ky_15_kuva2.jpg").exists(), "numerointi jatkui: ky_15_kuva2.jpg")
tarkista((P.KUVA_POLKU / "ky_15_kuva1.jpg").exists(), "ensimmäinen kuva säilyi")

print("\n[7] Kohteen poisto käsin sallii uudelleenlisäyksen")
(P.KUVA_POLKU / "ky_15_kuva1.jpg").unlink()
t4 = P.nimeä_kuvat(era1, gdf, et)
tarkista(t4["ok"] == 1, f"poistettu kuva saa mennä uudelleen läpi: {t4}")
tarkista((P.KUVA_POLKU / "ky_15_kuva1.jpg").exists(), "kuva palautui vapaaseen numeroon")

print("\n[8] Kirjanpitotiedosto")
led = json.loads((P.DATA_POLKU / P.KASITELLYT_TIEDOSTO).read_text(encoding="utf-8"))
tarkista(led.get("versio") == 1 and len(led["kuvat"]) == 3, f"kasitellyt.json: {len(led['kuvat'])} merkintää")
tarkista(all({"kohde", "tunnus", "lisatty"} <= set(v) for v in led["kuvat"].values()),
         "jokaisessa merkinnässä kohde/tunnus/lisatty")

print("\n[9] GeoJSON-vienti toimii yhä (kaikki kuvat mukaan)")
gpkg = BASE / "rakennukset.gpkg"
gdf.to_file(gpkg, layer="rakennukset", driver="GPKG")
tilastot = P.vie_geojson(gpkg, "rakennukset")
gj = json.loads((P.DATA_POLKU / "kohteet.geojson").read_text(encoding="utf-8"))
kuvat_15 = [f["properties"] for f in gj["features"] if f["properties"]["tunnus"] == "15"][0]
tarkista(tilastot["kuvilla"] == 2, f"molemmat rakennukset saivat kuvan: {tilastot}")
tarkista(kuvat_15["kuva1"].endswith("ky_15_kuva1.jpg") and kuvat_15["kuva2"].endswith("ky_15_kuva2.jpg"),
         "tunnukselle 15 kaksi kuva-URL:ää eri eristä")

print("\n" + "=" * 60)
print("KAIKKI OK" if not virheet else f"{len(virheet)} VIRHETTÄ:\n  - " + "\n  - ".join(virheet))
print("=" * 60)

if virheet:
    print(f"Väliaikaishakemisto jätettiin tutkimista varten: {BASE}")
else:
    shutil.rmtree(BASE, ignore_errors=True)
sys.exit(1 if virheet else 0)
