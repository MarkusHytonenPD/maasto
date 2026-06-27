"""
pipeline.py
===========
Rakennusdokumentoinnin pipeline — kenttäkuvista GitHub Pagesiin.

Vaiheet:
  1. GPX-geotägäys    (valinnainen, järjestelmäkameralle)
  2. Kuvien nimeäminen (EXIF GPS → lähin rakennus → ky_[tunnus]_kuva1.jpg)
  3. Git push          (kuvat)
  4. GeoJSON-vienti   (kuva1/2/3-sarakkeet täysillä URL:illa) + git push
  5. Yhteenveto

Vaatimukset:
  pip install geopandas pillow pyproj gpxpy piexif
  pip install tzdata   # vain Windows, zoneinfo-kirjaston aikavyöhyketietokanta

Konfiguroi PROJEKTI ja REPO_POLKU alla, muut johdetaan automaattisesti.
"""

import datetime
import re
import shutil
import subprocess
import zoneinfo
from pathlib import Path

_HELSINKI = zoneinfo.ZoneInfo("Europe/Helsinki")

try:
    import geopandas as gpd
    import gpxpy
    import piexif
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, TAGS
    from pyproj import Transformer
except ImportError as e:
    print(f"VIRHE: Kirjasto puuttuu: {e}")
    print("Asenna: pip install geopandas pillow pyproj gpxpy piexif")
    input("\nPaina Enter sulkeaksesi...")
    raise SystemExit(1)


# ══════════════════════════════════════════════════════════════════
#  KONFIGURAATIO — muuta PROJEKTI ja REPO_POLKU tarpeen mukaan
# ══════════════════════════════════════════════════════════════════

PROJEKTI      = "heinlansi"
REPO_POLKU    = Path(r"C:\GIS\maasto")
GITHUB_USER   = "MarkusHytonenPD"
GITHUB_REPO   = "maasto"
GITHUB_BRANCH = "main"
TUNNUS_SARAKE = "tunnus"

# Johdetaan automaattisesti — ei muuteta käsin
PROJEKTI_POLKU  = REPO_POLKU / "projektit" / PROJEKTI
KUVA_POLKU      = PROJEKTI_POLKU / "kuvat"
DATA_POLKU      = PROJEKTI_POLKU / "data"
GITHUB_BASE_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
    f"/{GITHUB_BRANCH}/projektit/{PROJEKTI}/kuvat/"
)

# Hakuetäisyydet metreinä
ETAISYYS_PUHELIN = 60
ETAISYYS_DRONE   = 300

# Kuvanimikaava: ky_[tunnus]_kuva[n].jpg
_KUVA_RE = re.compile(r"^ky_(.+)_kuva(\d+)\.jpg$", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════
#  EXIF-APUFUNKTIOT
# ══════════════════════════════════════════════════════════════════

def lue_exif_gps(kuvatiedosto: Path):
    """Lukee GPS-koordinaatin EXIF:stä. Palauttaa (lat, lon) tai None."""
    try:
        img = Image.open(kuvatiedosto)
        exif_data = img._getexif()
        if not exif_data:
            return None
        gps_info = {}
        for tag_id, value in exif_data.items():
            if TAGS.get(tag_id) == "GPSInfo":
                for gps_tag_id, gps_value in value.items():
                    gps_info[GPSTAGS.get(gps_tag_id, gps_tag_id)] = gps_value
        if not gps_info:
            return None

        def _muunna(arvo, ref):
            d = float(arvo[0]) + float(arvo[1]) / 60 + float(arvo[2]) / 3600
            return -d if ref in ("S", "W") else d

        return (
            _muunna(gps_info["GPSLatitude"],  gps_info["GPSLatitudeRef"]),
            _muunna(gps_info["GPSLongitude"], gps_info["GPSLongitudeRef"]),
        )
    except Exception:
        return None


def lue_exif_aikaleima(kuvatiedosto: Path) -> datetime.datetime | None:
    """Lukee DateTimeOriginal EXIF:stä. Palauttaa naive datetime tai None."""
    try:
        img = Image.open(kuvatiedosto)
        exif_data = img._getexif()
        if not exif_data:
            return None
        for tag_id, value in exif_data.items():
            if TAGS.get(tag_id) == "DateTimeOriginal":
                return datetime.datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def kirjoita_exif_gps(kuvatiedosto: Path, lat: float, lon: float) -> bool:
    """Kirjoittaa GPS-koordinaatin kuvan EXIF:iin in-place."""
    def _rationaali(arvo):
        arvo = abs(arvo)
        d = int(arvo)
        m = int((arvo - d) * 60)
        s = round((arvo - d - m / 60) * 3600 * 10000)
        return ((d, 1), (m, 1), (s, 10000))

    try:
        exif_dict = piexif.load(str(kuvatiedosto))
        exif_dict["GPS"] = {
            piexif.GPSIFD.GPSLatitudeRef:  b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude:     _rationaali(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude:    _rationaali(lon),
        }
        piexif.insert(piexif.dump(exif_dict), str(kuvatiedosto))
        return True
    except Exception as e:
        print(f"    ⚠ EXIF-kirjoitus epäonnistui ({kuvatiedosto.name}): {e}")
        return False


# ══════════════════════════════════════════════════════════════════
#  VAIHE 1 — GPX-GEOTÄGÄYS
# ══════════════════════════════════════════════════════════════════

def _lataa_gpx_pisteet(gpx_polku: Path) -> list[tuple]:
    """
    Palauttaa [(naive_datetime_helsinki, lat, lon), ...] järjestettynä.
    GPX-ajat muunnetaan Helsingin paikalliseksi ajaksi (kesä/talvi automaattisesti),
    jotta vertailu kameran EXIF-aikaan (paikallinen, ei timezone-tietoa) toimii.
    """
    with open(gpx_polku, encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    pisteet = []
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                if p.time:
                    if p.time.tzinfo is not None:
                        # UTC tai muu eksplisiittinen timezone → muunna Helsinkiin
                        t = p.time.astimezone(_HELSINKI).replace(tzinfo=None)
                    else:
                        # Ei timezone-tietoa — oletetaan jo paikallinen aika
                        t = p.time.replace(tzinfo=None)
                    pisteet.append((t, p.latitude, p.longitude))
    pisteet.sort(key=lambda x: x[0])
    return pisteet


def _interpoloi(pisteet: list[tuple], aikaleima: datetime.datetime):
    """Lineaarinen interpolointi. Palauttaa (lat, lon) tai None."""
    if not pisteet:
        return None
    if aikaleima < pisteet[0][0] or aikaleima > pisteet[-1][0]:
        return None
    for i in range(len(pisteet) - 1):
        t0, lat0, lon0 = pisteet[i]
        t1, lat1, lon1 = pisteet[i + 1]
        if t0 <= aikaleima <= t1:
            dt = (t1 - t0).total_seconds()
            f  = (aikaleima - t0).total_seconds() / dt if dt else 0
            return lat0 + f * (lat1 - lat0), lon0 + f * (lon1 - lon0)
    return None


def geotaggeri(kuvakansio: Path, gpx_polku: Path, aikaero_min: int):
    """Vaihe 1: kirjoittaa GPS-koordinaatin järjestelmäkamerakuvien EXIF:iin."""
    print("\n--- Vaihe 1: GPX-geotägäys ---")

    pisteet = _lataa_gpx_pisteet(gpx_polku)
    if not pisteet:
        print("  VIRHE: GPX-tiedostossa ei ole trackpisteitä.")
        return

    print(f"  {len(pisteet)} GPX-pistettä ladattu")
    if aikaero_min:
        print(f"  Aikaerokorjaus: {aikaero_min:+d} min")

    ok = ohitettu = 0
    for kuva in sorted(kuvakansio.glob("*.jpg")) + sorted(kuvakansio.glob("*.JPG")):
        if lue_exif_gps(kuva):
            continue  # Puhelin/drone-kuva — GPS jo tallessa

        ts = lue_exif_aikaleima(kuva)
        if not ts:
            print(f"  ⚠ {kuva.name}: ei EXIF-aikaleimaa — ohitetaan")
            ohitettu += 1
            continue

        # GPX-pisteet ovat jo Helsingin ajassa; aikaero_min korjaa
        # vain kameran kellon driftin suhteessa puhelimeen.
        korjattu = ts - datetime.timedelta(minutes=aikaero_min)
        koordinaatti = _interpoloi(pisteet, korjattu)
        if not koordinaatti:
            print(f"  ⚠ {kuva.name}: aikaleima {korjattu} GPX-radan ulkopuolella — ohitetaan")
            ohitettu += 1
            continue

        lat, lon = koordinaatti
        if kirjoita_exif_gps(kuva, lat, lon):
            print(f"  ✓ {kuva.name}: ({lat:.6f}, {lon:.6f})")
            ok += 1
        else:
            ohitettu += 1

    print(f"  Geotägätty: {ok} kuvaa, ohitettu: {ohitettu}")


# ══════════════════════════════════════════════════════════════════
#  VAIHE 2 — KUVIEN NIMEÄMINEN
# ══════════════════════════════════════════════════════════════════

_transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)


def _wgs84_etrs(lat: float, lon: float) -> tuple[float, float]:
    return _transformer.transform(lon, lat)


def _etsi_lahin(x: float, y: float, gdf, max_etaisyys: float):
    """Palauttaa (tunnus, etäisyys) tai None."""
    etaisyydet = gdf.geometry.distance(gpd.points_from_xy([x], [y])[0])
    idx = etaisyydet.idxmin()
    d   = etaisyydet[idx]
    if d <= max_etaisyys:
        return (gdf.loc[idx, TUNNUS_SARAKE], round(d, 1))
    return None


def _seuraava_numero(tunnus: str) -> int | None:
    """Palauttaa seuraavan vapaan kuvanumeron 1–3, tai None jos täynnä."""
    for n in range(1, 4):
        if not (KUVA_POLKU / f"ky_{tunnus}_kuva{n}.jpg").exists():
            return n
    return None


def nimeä_kuvat(kuvakansio: Path, gdf, max_etaisyys: float) -> dict:
    """
    Vaihe 2: nimeää kuvat ja kopioi KUVA_POLKU:hun.
    Palauttaa tilastotulen {ok, ohitettu, taynna}.
    """
    print("\n--- Vaihe 2: Kuvien nimeäminen ---")
    KUVA_POLKU.mkdir(parents=True, exist_ok=True)

    kuvat = sorted(kuvakansio.glob("*.jpg")) + sorted(kuvakansio.glob("*.JPG"))
    if not kuvat:
        print("  Kansiossa ei ole .jpg-tiedostoja.")
        return {"ok": 0, "ohitettu": 0, "taynna": 0}

    ok = ohitettu = taynna = 0

    for kuva in kuvat:
        gps = lue_exif_gps(kuva)
        if not gps:
            print(f"  ⚠ {kuva.name}: ei GPS EXIF:ssä — ohitetaan")
            ohitettu += 1
            continue

        lat, lon = gps
        x, y    = _wgs84_etrs(lat, lon)
        tulos   = _etsi_lahin(x, y, gdf, max_etaisyys)

        if not tulos:
            print(f"  ✗ {kuva.name}: ei rakennusta {max_etaisyys} m säteellä — ohitetaan")
            ohitettu += 1
            continue

        tunnus, etaisyys = tulos
        n = _seuraava_numero(tunnus)
        if n is None:
            print(f"  ⚠ {kuva.name}: tunnus {tunnus} jo 3 kuvaa — ohitetaan")
            taynna += 1
            continue

        uusi_nimi = f"ky_{tunnus}_kuva{n}.jpg".lower()
        shutil.copy2(kuva, KUVA_POLKU / uusi_nimi)
        print(f"  ✓ {kuva.name} → {uusi_nimi}  (tunnus={tunnus}, {etaisyys} m)")
        ok += 1

    print(f"  Nimetty: {ok}, ohitettu: {ohitettu}, täynnä: {taynna}")
    return {"ok": ok, "ohitettu": ohitettu, "taynna": taynna}


# ══════════════════════════════════════════════════════════════════
#  VAIHE 3 & 4b — GIT PUSH
# ══════════════════════════════════════════════════════════════════

def git_push(viesti: str, suhteellinen_polku: str):
    """git add → commit → push. Ohittaa push:n jos ei muutoksia."""
    print(f"  git add {suhteellinen_polku}")
    subprocess.run(
        ["git", "-C", str(REPO_POLKU), "add", suhteellinen_polku],
        check=True,
    )
    tulos = subprocess.run(
        ["git", "-C", str(REPO_POLKU), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    if not tulos.stdout.strip():
        print("  Ei muutoksia commitoitavaksi.")
        return
    subprocess.run(
        ["git", "-C", str(REPO_POLKU), "commit", "-m", viesti],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(REPO_POLKU), "push"],
        check=True,
    )
    print("  Push valmis.")


# ══════════════════════════════════════════════════════════════════
#  VAIHE 4 — GEOJSON-VIENTI
# ══════════════════════════════════════════════════════════════════

def _skannaa_kuvat() -> dict:
    """
    Skannaa KUVA_POLKU:n nykyisen tilan.
    Palauttaa {tunnus: [tiedostonimi, ...]} kaikille kuville,
    myös aiemmilta ajoilta.
    """
    kuva_map: dict[str, list[str]] = {}
    if not KUVA_POLKU.exists():
        return kuva_map
    for f in sorted(KUVA_POLKU.glob("ky_*_kuva*.jpg")):
        m = _KUVA_RE.match(f.name)
        if m:
            tunnus = m.group(1)
            kuva_map.setdefault(tunnus, []).append(f.name)
    return kuva_map


def vie_geojson(gpkg_polku: Path, layer_nimi: str) -> dict:
    """
    Vaihe 4: lukee GeoPackagen, lisää kuva1/2/3-URL:t, vie GeoJSON WGS84:ssä.
    Palauttaa tilastot {rakennuksia, kuvilla}.
    """
    print("\n--- Vaihe 4: GeoJSON-vienti ---")
    DATA_POLKU.mkdir(parents=True, exist_ok=True)

    gdf = gpd.read_file(gpkg_polku, layer=layer_nimi).to_crs("EPSG:4326")

    # Nollataan sarakkeet (ylikirjoitetaan aiempi ajo)
    gdf["kuva1"] = ""
    gdf["kuva2"] = ""
    gdf["kuva3"] = ""

    kuva_map = _skannaa_kuvat()
    for tunnus, tiedostot in kuva_map.items():
        maski = gdf[TUNNUS_SARAKE] == tunnus
        if not maski.any():
            print(f"  ⚠ Tunnusta '{tunnus}' ei löydy GeoPackagesta")
            continue
        for i, nimi in enumerate(tiedostot[:3], start=1):
            gdf.loc[maski, f"kuva{i}"] = GITHUB_BASE_URL + nimi

    kohde = DATA_POLKU / "kohteet.geojson"
    gdf.to_file(kohde, driver="GeoJSON")
    print(f"  Viety: {kohde}")

    kuvilla = sum(1 for t in gdf[TUNNUS_SARAKE] if t in kuva_map)
    print(f"  {len(gdf)} rakennusta, {kuvilla} sai kuvan")
    return {"rakennuksia": len(gdf), "kuvilla": kuvilla}


# ══════════════════════════════════════════════════════════════════
#  PÄÄOHJELMA
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  Rakennusdokumentoinnin pipeline")
    print(f"  Projekti: {PROJEKTI}")
    print("=" * 60)
    print()

    # --- Kyselyt ---

    kuvakansio_str = input("Kuvakansio (polku):\n> ").strip().strip('"')
    kuvakansio = Path(kuvakansio_str)
    if not kuvakansio.is_dir():
        print(f"VIRHE: Kansiota ei löydy: {kuvakansio}")
        input("Paina Enter sulkeaksesi...")
        return

    gpkg_polku_str = input("\nGeoPackage-tiedosto (polku):\n> ").strip().strip('"')
    gpkg_polku = Path(gpkg_polku_str)
    if not gpkg_polku.is_file():
        print(f"VIRHE: Tiedostoa ei löydy: {gpkg_polku}")
        input("Paina Enter sulkeaksesi...")
        return

    layer_nimi = input("\nLayer-nimi GeoPackagessa:\n> ").strip()

    print(f"\nKuvatyyppi?")
    print(f"  1 = Puhelin  (hakuetäisyys {ETAISYYS_PUHELIN} m)")
    print(f"  2 = Drone    (hakuetäisyys {ETAISYYS_DRONE} m)")
    kuvatyyppi_val = input("Valinta (1/2): ").strip()
    if kuvatyyppi_val == "1":
        max_etaisyys = ETAISYYS_PUHELIN
    elif kuvatyyppi_val == "2":
        max_etaisyys = ETAISYYS_DRONE
    else:
        print("Virheellinen valinta.")
        input("Paina Enter sulkeaksesi...")
        return

    gpx_polku   = None
    aikaero_min = 0
    if input("\nOnko mukana GPX-tiedosto järjestelmäkameralle? (k/e): ").strip().lower() == "k":
        gpx_polku_str = input("GPX-tiedoston polku:\n> ").strip().strip('"')
        gpx_polku = Path(gpx_polku_str)
        if not gpx_polku.is_file():
            print(f"VIRHE: GPX-tiedostoa ei löydy: {gpx_polku}")
            input("Paina Enter sulkeaksesi...")
            return
        try:
            aikaero_min = int(
                input(
                    "Kameran kellodrifti minuutteina (0 jos synkronoitu puhelimeen):\n"
                    "  Aikavyöhyke hoidetaan automaattisesti.\n> "
                ).strip()
            )
        except ValueError:
            print("VIRHE: Aikaero pitää olla kokonaisluku.")
            input("Paina Enter sulkeaksesi...")
            return

    # --- Ladataan GeoPackage (EPSG:3067 tilaoperaatioihin) ---

    print("\nLadataan rakennusdata...")
    try:
        gdf_3067 = gpd.read_file(gpkg_polku, layer=layer_nimi).to_crs("EPSG:3067")
        print(f"  {len(gdf_3067)} rakennusta ladattu.")
    except Exception as e:
        print(f"VIRHE: GeoPackagea ei voitu lukea:\n{e}")
        input("Paina Enter sulkeaksesi...")
        return

    # --- Vaihe 1: GPX-geotägäys ---

    if gpx_polku:
        geotaggeri(kuvakansio, gpx_polku, aikaero_min)

    # --- Vaihe 2: Kuvien nimeäminen ---

    tilastot = nimeä_kuvat(kuvakansio, gdf_3067, max_etaisyys)

    # --- Vaihe 3: Git push — kuvat ---

    print("\n--- Vaihe 3: Git push (kuvat) ---")
    git_push(
        f"Lisää kenttäkuvat: {PROJEKTI}",
        f"projektit/{PROJEKTI}/kuvat/",
    )

    # --- Vaihe 4: GeoJSON-vienti + git push ---

    geojson_tilastot = vie_geojson(gpkg_polku, layer_nimi)

    print("\n--- Vaihe 4b: Git push (data) ---")
    git_push(
        f"Päivitä kohteet.geojson: {PROJEKTI}",
        f"projektit/{PROJEKTI}/data/",
    )

    # --- Vaihe 5: Yhteenveto ---

    print()
    print("=" * 60)
    print("  Valmis!")
    print(f"  Kuvia nimetty:       {tilastot['ok']}")
    if tilastot["ohitettu"]:
        print(f"  Ohitettu:            {tilastot['ohitettu']}  (ei GPS tai ei rakennusta lähellä)")
    if tilastot["taynna"]:
        print(f"  Täynnä:              {tilastot['taynna']}  (rakennuksella jo 3 kuvaa)")
    print(f"  Rakennuksia kuvilla: {geojson_tilastot['kuvilla']} / {geojson_tilastot['rakennuksia']}")
    print("=" * 60)
    input("\nPaina Enter sulkeaksesi...")


if __name__ == "__main__":
    main()
