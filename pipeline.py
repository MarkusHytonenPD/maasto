"""
pipeline.py
===========
Rakennusdokumentoinnin pipeline — kenttäkuvista GitHub Pagesiin.

Vaiheet:
  1. GPX-geotägäys    (valinnainen, järjestelmäkameralle; monta GPX:ää sallittu)
  2. Kuvien nimeäminen (EXIF GPS → lähin rakennus → ky_[tunnus]_kuva1.jpg)
  3. Git push          (kuvat)
  4. GeoJSON-vienti   (kuva1/2/3-sarakkeet täysillä URL:illa) + git push
  5. Yhteenveto

Työskentely erissä:
  Kuvia ja GPX-lokeja voi lisätä useassa ajossa. Kuvanumerointi jatkuu siitä
  mihin edellinen ajo jäi, ja GeoJSON rakennetaan aina koko kuvat/-kansiosta.
  Jo käsitellyt lähdekuvat kirjataan data/kasitellyt.json:iin, joten sama kuva
  ei kopioidu kahdesti vaikka se olisi mukana useammassa ajossa.
  GPX-lokeja voi antaa monta (tai kansion) — pisteet yhdistetään aikajärjestykseen,
  eikä pitkien aukkojen (loggeri pois päältä) yli interpoloida.

Vaatimukset:
  pip install geopandas pillow pyproj gpxpy piexif
  pip install tzdata   # vain Windows, zoneinfo-kirjaston aikavyöhyketietokanta

Konfiguroi PROJEKTI ja REPO_POLKU alla, muut johdetaan automaattisesti.
"""

import datetime
import json
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

REPO_POLKU    = Path("/home/markus/omat-apit/rak_kult_kuvakarttajulkaisu")  # Windows: Path(r"C:\GIS\maasto")
GITHUB_USER   = "MarkusHytonenPD"
GITHUB_REPO   = "maasto"
GITHUB_BRANCH = "main"
TUNNUS_SARAKE = "tunnus"

# Asetetaan main():ssä käyttäjän syötteen perusteella
PROJEKTI        = ""
PROJEKTI_POLKU  = Path()
KUVA_POLKU      = Path()
DATA_POLKU      = Path()
GITHUB_BASE_URL = ""

# Oletushakuetäisyydet metreinä (kysytään ajon alussa, nämä ovat oletuksia)
ETAISYYS_PUHELIN       = 60
ETAISYYS_DRONE         = 300
ETAISYYS_JARJ_KAMERA   = 300

# Suurin GPX-pisteväli jonka yli interpoloidaan (minuuttia, kysytään ajon alussa).
# Pidempi väli = loggeri on ollut pois päältä → kuvan sijaintia ei voi päätellä.
MAX_GPX_AUKKO_MIN = 10

# Kirjanpito jo käsitellyistä lähdekuvista (DATA_POLKU:n alla, menee gitiin)
KASITELLYT_TIEDOSTO = "kasitellyt.json"

# EXIF Make -tunnistus laitteelle
_DRONE_MAKE = {"dji", "autel", "parrot", "skydio", "yuneec"}
_PHONE_MAKE = {"apple", "samsung", "google", "huawei", "xiaomi", "oneplus", "motorola", "lg"}

# Kuvanimikaava: ky_[tunnus]_kuva[n].jpg
_KUVA_RE = re.compile(r"^ky_(.+)_kuva(\d+)\.jpg$", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════
#  EXIF-APUFUNKTIOT
# ══════════════════════════════════════════════════════════════════

def _tunnista_laite(kuvatiedosto: Path) -> str:
    """Palauttaa 'puhelin', 'drone' tai 'jarjestelmakamera' EXIF Make-kentän perusteella."""
    try:
        img = Image.open(kuvatiedosto)
        exif_data = img._getexif()
        if exif_data:
            for tag_id, value in exif_data.items():
                if TAGS.get(tag_id) == "Make":
                    make = str(value).strip().lower()
                    if any(d in make for d in _DRONE_MAKE):
                        return "drone"
                    if any(p in make for p in _PHONE_MAKE):
                        return "puhelin"
                    return "jarjestelmakamera"
    except Exception:
        pass
    return "jarjestelmakamera"  # oletus jos Make puuttuu

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

def _lataa_gpx_pisteet(gpx_polut: list[Path]) -> list[tuple]:
    """
    Lukee yhden tai useamman GPX:n ja palauttaa
    [(naive_datetime_helsinki, lat, lon), ...] aikajärjestyksessä.
    GPX-ajat muunnetaan Helsingin paikalliseksi ajaksi (kesä/talvi automaattisesti),
    jotta vertailu kameran EXIF-aikaan (paikallinen, ei timezone-tietoa) toimii.
    Useamman lokin pisteet yhdistetään; päällekkäiset aikaleimat karsitaan.
    """
    if isinstance(gpx_polut, (str, Path)):      # yksi polku käy myös sellaisenaan
        gpx_polut = [Path(gpx_polut)]

    pisteet = []
    for gpx_polku in gpx_polut:
        try:
            with open(gpx_polku, encoding="utf-8") as f:
                gpx = gpxpy.parse(f)
        except Exception as e:
            print(f"  ⚠ {gpx_polku.name}: ei voitu lukea ({e}) — ohitetaan")
            continue
        ennen = len(pisteet)
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
        print(f"    {gpx_polku.name}: {len(pisteet) - ennen} pistettä")

    pisteet.sort(key=lambda x: x[0])

    # Päällekkäin menevät lokit voivat sisältää saman hetken kahdesti
    uniikit: list[tuple] = []
    for p in pisteet:
        if not uniikit or p[0] != uniikit[-1][0]:
            uniikit.append(p)
    if len(uniikit) < len(pisteet):
        print(f"    ({len(pisteet) - len(uniikit)} päällekkäistä aikaleimaa karsittu)")
    return uniikit


def _aukot(pisteet: list[tuple], max_aukko_s: float) -> list[tuple]:
    """Palauttaa [(alku, loppu, kesto_min), ...] väleistä jotka ylittävät rajan."""
    tulos = []
    for i in range(len(pisteet) - 1):
        dt = (pisteet[i + 1][0] - pisteet[i][0]).total_seconds()
        if dt > max_aukko_s:
            tulos.append((pisteet[i][0], pisteet[i + 1][0], dt / 60))
    return tulos


def _interpoloi(pisteet: list[tuple], aikaleima: datetime.datetime, max_aukko_s: float):
    """
    Lineaarinen interpolointi. Palauttaa ((lat, lon), None) tai (None, syy).
    Pisteväliä joka on pidempi kuin max_aukko_s ei interpoloida yli — silloin
    loggeri on ollut pois päältä eikä kuvan sijaintia voi päätellä.
    """
    if not pisteet:
        return None, "ei GPX-pisteitä"
    if aikaleima < pisteet[0][0] or aikaleima > pisteet[-1][0]:
        return None, "aikaleima GPX-lokien ulkopuolella"
    for i in range(len(pisteet) - 1):
        t0, lat0, lon0 = pisteet[i]
        t1, lat1, lon1 = pisteet[i + 1]
        if t0 <= aikaleima <= t1:
            dt = (t1 - t0).total_seconds()
            if dt > max_aukko_s:
                return None, (f"GPX-aukko {dt / 60:.0f} min ({t0:%d.%m. %H:%M}–{t1:%d.%m. %H:%M}) "
                              f"— loggeri pois päältä?")
            f = (aikaleima - t0).total_seconds() / dt if dt else 0
            return (lat0 + f * (lat1 - lat0), lon0 + f * (lon1 - lon0)), None
    return None, "ei sopivaa GPX-väliä"


def geotaggeri(kuvakansio: Path, gpx_polut: list[Path], aikaero_min: int,
               max_aukko_min: int = MAX_GPX_AUKKO_MIN):
    """Vaihe 1: kirjoittaa GPS-koordinaatin järjestelmäkamerakuvien EXIF:iin."""
    print("\n--- Vaihe 1: GPX-geotägäys ---")

    pisteet = _lataa_gpx_pisteet(gpx_polut)
    if not pisteet:
        print("  VIRHE: GPX-tiedostoissa ei ole trackpisteitä.")
        return

    max_aukko_s = max_aukko_min * 60
    print(f"  {len(pisteet)} GPX-pistettä ladattu "
          f"({pisteet[0][0]:%d.%m. %H:%M} – {pisteet[-1][0]:%d.%m. %H:%M})")
    aukot = _aukot(pisteet, max_aukko_s)
    if aukot:
        print(f"  {len(aukot)} aukkoa yli {max_aukko_min} min — näiden yli ei interpoloida:")
        for alku, loppu, kesto in aukot[:5]:
            print(f"    {alku:%d.%m. %H:%M} – {loppu:%d.%m. %H:%M}  ({kesto:.0f} min)")
        if len(aukot) > 5:
            print(f"    ... ja {len(aukot) - 5} muuta")
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
        koordinaatti, syy = _interpoloi(pisteet, korjattu, max_aukko_s)
        if not koordinaatti:
            print(f"  ⚠ {kuva.name} ({korjattu:%d.%m. %H:%M}): {syy} — ohitetaan")
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
#  GEOPACKAGE-LUKEMINEN
# ══════════════════════════════════════════════════════════════════

def _lue_ja_normalisoi_crs(gpkg_polku: Path, layer_nimi: str, kohde_crs: str):
    """
    Lukee GeoPackagen ja varmistaa oikean CRS:n.
    Korjaa tiedostot joissa CRS on 'Undefined' mutta koordinaatit
    ovat jo EPSG:3067-metreissä (yleinen QGIS-exportointivirhe).
    """
    gdf = gpd.read_file(gpkg_polku, layer=layer_nimi)
    if gdf.crs is None or "Undefined" in str(gdf.crs) or "unknown" in str(gdf.crs).lower():
        gdf = gdf.set_crs("EPSG:3067", allow_override=True)
        print("  Huom: CRS tunnistamaton — oletettu EPSG:3067")
    return gdf.to_crs(kohde_crs)


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
        return (str(gdf.loc[idx, TUNNUS_SARAKE]), round(d, 1))
    return None


def _seuraava_numero(tunnus: str) -> int | None:
    """Palauttaa seuraavan vapaan kuvanumeron 1–3, tai None jos täynnä."""
    for n in range(1, 4):
        if not (KUVA_POLKU / f"ky_{tunnus}_kuva{n}.jpg").exists():
            return n
    return None


# ══════════════════════════════════════════════════════════════════
#  KÄSITELTYJEN LÄHDEKUVIEN KIRJANPITO (duplikaattisuoja erissä ajettaessa)
# ══════════════════════════════════════════════════════════════════

def _kuva_avain(kuva: Path) -> str:
    """
    Lähdekuvan tunniste: tiedostonimi + EXIF-kuvausaika. Aikaleima ei muutu
    vaikka geotägäys kirjoittaisi kuvaan GPS:n (tiedostokoko muuttuisi), joten
    sama kuva tunnistetaan myös geotägäyksen jälkeen. Ilman aikaleimaa
    (näitä geotägäys ei muuta) käytetään tiedostokokoa.
    """
    ts = lue_exif_aikaleima(kuva)
    if ts:
        return f"{kuva.name.lower()}|{ts.isoformat()}"
    try:
        return f"{kuva.name.lower()}|koko:{kuva.stat().st_size}"
    except OSError:
        return kuva.name.lower()


def _lue_kasitellyt() -> dict:
    """Lukee data/kasitellyt.json → {avain: {kohde, tunnus, lisatty}}."""
    polku = DATA_POLKU / KASITELLYT_TIEDOSTO
    if not polku.exists():
        return {}
    try:
        return json.loads(polku.read_text(encoding="utf-8")).get("kuvat", {})
    except Exception as e:
        print(f"  ⚠ {KASITELLYT_TIEDOSTO} ei aukea ({e}) — aloitetaan tyhjästä kirjanpidosta")
        return {}


def _kirjoita_kasitellyt(kasitellyt: dict):
    DATA_POLKU.mkdir(parents=True, exist_ok=True)
    (DATA_POLKU / KASITELLYT_TIEDOSTO).write_text(
        json.dumps({"versio": 1, "kuvat": kasitellyt}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _merkitse_kasitellyksi(kasitellyt: dict, avain: str, kohde: str, tunnus: str):
    kasitellyt[avain] = {
        "kohde":   kohde,
        "tunnus":  tunnus,
        "lisatty": datetime.datetime.now().replace(microsecond=0).isoformat(),
    }
    _kirjoita_kasitellyt(kasitellyt)


def _jo_kasitelty(kasitellyt: dict, avain: str) -> str | None:
    """
    Palauttaa kohdetiedoston nimen jos kuva on jo viety JA tiedosto on yhä
    paikallaan. Jos kohde on poistettu käsin (= halutaan korvata), palauttaa
    None eli kuva saa mennä uudelleen läpi.
    """
    tieto = kasitellyt.get(avain)
    if not tieto:
        return None
    kohde = tieto.get("kohde", "")
    if kohde and (KUVA_POLKU / kohde).exists():
        return kohde
    return None


def nimeä_kuvat(kuvakansio: Path, gdf, etaisyydet: dict) -> dict:
    """
    Vaihe 2: nimeää kuvat ja kopioi KUVA_POLKU:hun.
    etaisyydet = {"puhelin": m, "drone": m, "jarjestelmakamera": m}
    Aiemmissa ajoissa käsitellyt lähdekuvat ohitetaan (data/kasitellyt.json).
    Palauttaa tilastot {ok, ohitettu, taynna, duplikaatti}.
    """
    print("\n--- Vaihe 2: Kuvien nimeäminen ---")
    KUVA_POLKU.mkdir(parents=True, exist_ok=True)

    kuvat = sorted(kuvakansio.glob("*.jpg")) + sorted(kuvakansio.glob("*.JPG"))
    if not kuvat:
        print("  Kansiossa ei ole .jpg-tiedostoja.")
        return {"ok": 0, "ohitettu": 0, "taynna": 0, "duplikaatti": 0}

    kasitellyt = _lue_kasitellyt()
    if kasitellyt:
        print(f"  Kirjanpidossa {len(kasitellyt)} aiemmin käsiteltyä kuvaa")

    ok = ohitettu = taynna = duplikaatti = 0

    for kuva in kuvat:
        avain  = _kuva_avain(kuva)
        aiempi = _jo_kasitelty(kasitellyt, avain)
        if aiempi:
            print(f"  ↺ {kuva.name}: käsitelty jo aiemmin → {aiempi} — ohitetaan")
            duplikaatti += 1
            continue

        gps = lue_exif_gps(kuva)
        if not gps:
            print(f"  ⚠ {kuva.name}: ei GPS EXIF:ssä — ohitetaan")
            ohitettu += 1
            continue

        laite       = _tunnista_laite(kuva)
        max_et      = etaisyydet.get(laite, etaisyydet["drone"])
        lat, lon    = gps
        x, y        = _wgs84_etrs(lat, lon)
        tulos       = _etsi_lahin(x, y, gdf, max_et)

        if not tulos:
            print(f"  ✗ {kuva.name} [{laite}]: ei rakennusta {max_et} m säteellä — ohitetaan")
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
        _merkitse_kasitellyksi(kasitellyt, avain, uusi_nimi, tunnus)
        print(f"  ✓ {kuva.name} [{laite}] → {uusi_nimi}  (tunnus={tunnus}, {etaisyys} m)")
        ok += 1

    print(f"  Nimetty: {ok}, ohitettu: {ohitettu}, täynnä: {taynna}, "
          f"jo käsitelty: {duplikaatti}")
    return {"ok": ok, "ohitettu": ohitettu, "taynna": taynna, "duplikaatti": duplikaatti}


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
    # Tarkistetaan vain stagetetut muutokset (--cached), ei working tree -muutoksia
    tulos = subprocess.run(
        ["git", "-C", str(REPO_POLKU), "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if tulos.returncode == 0:  # 0 = ei stagetuita muutoksia
        print("  Ei muutoksia commitoitavaksi.")
        return
    subprocess.run(
        ["git", "-C", str(REPO_POLKU), "commit", "-m", viesti],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(REPO_POLKU), "push", "--set-upstream", "origin", "main"],
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

    gdf = _lue_ja_normalisoi_crs(gpkg_polku, layer_nimi, "EPSG:4326")

    # Nollataan sarakkeet (ylikirjoitetaan aiempi ajo)
    gdf["kuva1"] = ""
    gdf["kuva2"] = ""
    gdf["kuva3"] = ""

    # Normalisoidaan tunnus merkkijonoksi — GeoPackagessa voi olla int tai str
    gdf[TUNNUS_SARAKE] = gdf[TUNNUS_SARAKE].astype(str)

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
#  PROJEKTICONFIG
# ══════════════════════════════════════════════════════════════════

def alusta_projekticonfig():
    """Luo config.json-pohjan ja docs/[projekti]/index.html jos niitä ei vielä ole."""
    PROJEKTI_POLKU.mkdir(parents=True, exist_ok=True)

    kohde_cfg = PROJEKTI_POLKU / "config.json"
    if not kohde_cfg.exists():
        pohja = {"nimi": PROJEKTI, "tasot": []}
        kohde_cfg.write_text(json.dumps(pohja, ensure_ascii=False, indent=4), encoding="utf-8")
        print(f"  Luotu: {kohde_cfg}  (lisää WMS-tasot tähän tarvittaessa)")

    docs_projekti = REPO_POLKU / "docs" / PROJEKTI
    docs_projekti.mkdir(parents=True, exist_ok=True)
    kohde_html = docs_projekti / "index.html"
    if not kohde_html.exists():
        html = f"""\
<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{PROJEKTI}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="../kartta.css" />
</head>
<body>

<div id="map"></div>

<div id="lightbox">
  <span id="lightbox-sulje" title="Sulje">&#x2715;</span>
  <img id="lightbox-kuva" src="" alt="" />
</div>

<script>window.PROJEKTI = "{PROJEKTI}";</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/proj4@2.11.0/dist/proj4.js"></script>
<script src="https://unpkg.com/proj4leaflet@1.0.2/src/proj4leaflet.js"></script>
<script src="../config.js"></script>
<script src="../kartta.js"></script>

</body>
</html>
"""
        kohde_html.write_text(html, encoding="utf-8")
        print(f"  Luotu: {kohde_html}")


# ══════════════════════════════════════════════════════════════════
#  KÄSIN SIJOITTELU
# ══════════════════════════════════════════════════════════════════

def sijoita_käsin(gdf) -> int:
    """
    Käyttäjä antaa tunnuksen ja kuvan polun toistuvasti.
    Kopioi kuvan KUVA_POLKU:hun seuraavaan vapaaseen numeroon.
    Lisäys kirjataan kirjanpitoon, jotta pipeline-ajo ei kopioi samaa kuvaa
    uudelleen. Käsin lisättäessä duplikaatista vain varoitetaan — valinta on
    tietoinen, joten se ei estä.
    Palauttaa lisättyjen kuvien määrän.
    """
    print("\n--- Käsin sijoittelu ---")
    print("  Anna tunnus ja kuvan polku. Tyhjä tunnus lopettaa.")
    KUVA_POLKU.mkdir(parents=True, exist_ok=True)

    tunnukset  = set(gdf[TUNNUS_SARAKE].astype(str))
    kasitellyt = _lue_kasitellyt()
    lisatty = 0

    while True:
        tunnus = input("\n  Tunnus (tai tyhjä lopettaaksesi):\n  > ").strip()
        if not tunnus:
            break
        if tunnus not in tunnukset:
            print(f"  ⚠ Tunnusta '{tunnus}' ei löydy aineistosta")
            continue

        kuva_str = input("  Kuvan polku:\n  > ").strip().strip('"')
        kuva = Path(kuva_str)
        if not kuva.is_file():
            print(f"  ⚠ Tiedostoa ei löydy: {kuva}")
            continue
        if kuva.suffix.lower() != ".jpg":
            print(f"  ⚠ Vain .jpg-tiedostot tuettu")
            continue

        n = _seuraava_numero(tunnus)
        if n is None:
            print(f"  ⚠ Tunnuksella {tunnus} on jo 3 kuvaa — ei lisätä")
            continue

        avain  = _kuva_avain(kuva)
        aiempi = _jo_kasitelty(kasitellyt, avain)
        if aiempi:
            print(f"  ⚠ Sama kuva on jo viety nimellä {aiempi} — lisätään silti")

        uusi_nimi = f"ky_{tunnus}_kuva{n}.jpg".lower()
        shutil.copy2(kuva, KUVA_POLKU / uusi_nimi)
        _merkitse_kasitellyksi(kasitellyt, avain, uusi_nimi, tunnus)
        print(f"  ✓ {kuva.name} → {uusi_nimi}")
        lisatty += 1

    print(f"\n  Lisätty: {lisatty} kuvaa")
    return lisatty


# ══════════════════════════════════════════════════════════════════
#  PÄÄOHJELMA
# ══════════════════════════════════════════════════════════════════

def _kysy_gpx_polut() -> list[Path]:
    """
    Kysyy GPX-tiedostoja rivi kerrallaan — loggeri tuottaa useita lokeja
    (esim. yksi per päivä). Kansiopolku hyväksytään: siitä otetaan kaikki
    .gpx-tiedostot. Tyhjä rivi lopettaa.
    """
    print("\nGPX-tiedostot — yksi polku per rivi, tai kansio (kaikki sen .gpx-tiedostot).")
    print("Tyhjä rivi lopettaa.")
    polut: list[Path] = []
    while True:
        syote = input("  > ").strip().strip('"')
        if not syote:
            break
        polku = Path(syote)
        if polku.is_dir():
            loydetyt = sorted(set(polku.glob("*.gpx")) | set(polku.glob("*.GPX")))
            if not loydetyt:
                print(f"    ⚠ Kansiossa ei ole .gpx-tiedostoja: {polku}")
                continue
            for g in loydetyt:
                print(f"    + {g.name}")
            polut.extend(loydetyt)
        elif polku.is_file():
            print(f"    + {polku.name}")
            polut.append(polku)
        else:
            print(f"    ⚠ Ei löydy: {polku}")

    # Sama tiedosto voi tulla sekä suoraan että kansion kautta
    uniikit = list(dict.fromkeys(p.resolve() for p in polut))
    if uniikit:
        print(f"  Yhteensä {len(uniikit)} GPX-tiedostoa")
    return uniikit


def main():
    global PROJEKTI, PROJEKTI_POLKU, KUVA_POLKU, DATA_POLKU, GITHUB_BASE_URL

    PROJEKTI = input("Projekti:\n> ").strip()
    if not PROJEKTI:
        print("VIRHE: Projektinimi ei voi olla tyhjä.")
        input("Paina Enter sulkeaksesi...")
        return

    PROJEKTI_POLKU  = REPO_POLKU / "projektit" / PROJEKTI
    KUVA_POLKU      = PROJEKTI_POLKU / "kuvat"
    DATA_POLKU      = PROJEKTI_POLKU / "data"
    GITHUB_BASE_URL = (
        f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
        f"/{GITHUB_BRANCH}/projektit/{PROJEKTI}/kuvat/"
    )

    alusta_projekticonfig()
    git_push(f"Alusta projekti: {PROJEKTI}", f"docs/{PROJEKTI}/")

    print()
    print("=" * 60)
    print("  Rakennusdokumentoinnin pipeline")
    print(f"  Projekti: {PROJEKTI}")
    print("=" * 60)
    print()

    # --- Kyselyt ---

    gpkg_polku_str = input("GeoPackage-tiedosto (polku):\n> ").strip().strip('"')
    gpkg_polku = Path(gpkg_polku_str)
    if not gpkg_polku.is_file():
        print(f"VIRHE: Tiedostoa ei löydy: {gpkg_polku}")
        input("Paina Enter sulkeaksesi...")
        return

    layer_nimi = input("\nLayer-nimi GeoPackagessa:\n> ").strip()

    # --- Tila ---

    print("\nTila?")
    print("  1 = Pipeline  (automaattinen, kuvakansio → GPS → nimeäminen)")
    print("  2 = Sijoita käsin  (lisää tai korjaa yksittäisiä kuvia)")
    tila = input("Valinta (1/2): ").strip()
    if tila not in ("1", "2"):
        print("Virheellinen valinta.")
        input("Paina Enter sulkeaksesi...")
        return

    # --- Ladataan GeoPackage (EPSG:3067 tilaoperaatioihin) ---

    print("\nLadataan rakennusdata...")
    try:
        gdf_3067 = _lue_ja_normalisoi_crs(gpkg_polku, layer_nimi, "EPSG:3067")
        gdf_3067[TUNNUS_SARAKE] = gdf_3067[TUNNUS_SARAKE].astype(str)
        print(f"  {len(gdf_3067)} rakennusta ladattu.")
    except Exception as e:
        print(f"VIRHE: GeoPackagea ei voitu lukea:\n{e}")
        input("Paina Enter sulkeaksesi...")
        return

    # ── TILA 1: PIPELINE ──────────────────────────────────────────

    if tila == "1":

        kuvakansio_str = input("\nKuvakansio (polku):\n> ").strip().strip('"')
        kuvakansio = Path(kuvakansio_str)
        if not kuvakansio.is_dir():
            print(f"VIRHE: Kansiota ei löydy: {kuvakansio}")
            input("Paina Enter sulkeaksesi...")
            return

        def _kysy_etaisyys(nimi: str, oletus: int) -> int:
            arvo = input(f"  {nimi} [{oletus} m]: ").strip()
            return int(arvo) if arvo else oletus

        print("\nHakuetäisyydet (Enter = oletus):")
        try:
            etaisyydet = {
                "puhelin":        _kysy_etaisyys("Puhelin       ", ETAISYYS_PUHELIN),
                "drone":          _kysy_etaisyys("Drone         ", ETAISYYS_DRONE),
                "jarjestelmakamera": _kysy_etaisyys("Järj.kamera   ", ETAISYYS_JARJ_KAMERA),
            }
        except ValueError:
            print("VIRHE: Etäisyyden pitää olla kokonaisluku.")
            input("Paina Enter sulkeaksesi...")
            return

        gpx_polut     = []
        aikaero_min   = 0
        max_aukko_min = MAX_GPX_AUKKO_MIN
        if input("\nOnko mukana GPX-tiedostoja järjestelmäkameralle? (k/e): ").strip().lower() == "k":
            gpx_polut = _kysy_gpx_polut()
            if not gpx_polut:
                print("VIRHE: Yhtään GPX-tiedostoa ei annettu.")
                input("Paina Enter sulkeaksesi...")
                return
            try:
                aikaero_min = int(
                    input(
                        "\nKameran kellodrifti minuutteina (0 jos synkronoitu puhelimeen):\n"
                        "  Aikavyöhyke hoidetaan automaattisesti.\n> "
                    ).strip()
                )
            except ValueError:
                print("VIRHE: Aikaero pitää olla kokonaisluku.")
                input("Paina Enter sulkeaksesi...")
                return
            try:
                arvo = input(
                    f"\nSuurin sallittu aukko GPX-pisteiden välissä minuutteina [{MAX_GPX_AUKKO_MIN}]:\n"
                    "  Pidempien aukkojen (loggeri pois päältä esim. yöksi) yli ei\n"
                    "  interpoloida — niihin osuvat kuvat ohitetaan.\n> "
                ).strip()
                max_aukko_min = int(arvo) if arvo else MAX_GPX_AUKKO_MIN
            except ValueError:
                print("VIRHE: Aukon pitää olla kokonaisluku.")
                input("Paina Enter sulkeaksesi...")
                return

        if gpx_polut:
            geotaggeri(kuvakansio, gpx_polut, aikaero_min, max_aukko_min)

        tilastot = nimeä_kuvat(kuvakansio, gdf_3067, etaisyydet)
        kuvia_lisatty = tilastot["ok"]

        if kuvia_lisatty > 0:
            print("\n--- Vaihe 3: Git push (kuvat) ---")
            git_push(
                f"Lisää kenttäkuvat: {PROJEKTI}",
                f"projektit/{PROJEKTI}/kuvat/",
            )
        else:
            print("\nVaihe 3 ohitettu — ei nimetty yhtään kuvaa.")

    # ── TILA 2: KÄSIN SIJOITTELU ──────────────────────────────────

    else:
        kuvia_lisatty = sijoita_käsin(gdf_3067)

        if kuvia_lisatty > 0:
            print("\n--- Git push (kuvat) ---")
            git_push(
                f"Lisää kenttäkuvat: {PROJEKTI}",
                f"projektit/{PROJEKTI}/kuvat/",
            )

        tilastot = {"ok": kuvia_lisatty, "ohitettu": 0, "taynna": 0, "duplikaatti": 0}

    # ── YHTEINEN LOPPU: GEOJSON + PUSH ────────────────────────────

    geojson_tilastot = vie_geojson(gpkg_polku, layer_nimi)

    print("\n--- Git push (data) ---")
    git_push(
        f"Päivitä kohteet.geojson: {PROJEKTI}",
        f"projektit/{PROJEKTI}/data/",
    )

    print()
    print("=" * 60)
    print("  Valmis!")
    print(f"  Kuvia lisätty:       {tilastot['ok']}")
    if tilastot.get("ohitettu"):
        print(f"  Ohitettu:            {tilastot['ohitettu']}  (ei GPS tai ei rakennusta lähellä)")
    if tilastot.get("taynna"):
        print(f"  Täynnä:              {tilastot['taynna']}  (rakennuksella jo 3 kuvaa)")
    if tilastot.get("duplikaatti"):
        print(f"  Jo käsitelty:        {tilastot['duplikaatti']}  (viety jo aiemmassa ajossa)")
    print(f"  Rakennuksia kuvilla: {geojson_tilastot['kuvilla']} / {geojson_tilastot['rakennuksia']}")
    print("=" * 60)
    input("\nPaina Enter sulkeaksesi...")


if __name__ == "__main__":
    main()
