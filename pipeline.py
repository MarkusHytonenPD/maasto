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

Tilat:
  1 = Pipeline (automaattinen kuvakansiosta)
  2 = Sijoita käsin (yksittäiset kuvat)
  3 = Päivitä luokitukset GeoPackageen — yhdistää karttasovelluksesta ladatun
      kaavoittajan luokitus-GeoJSONin ja viranomaisten kommentit (Sheetsistä
      julkisena CSV:nä) alkuperäiseen GeoPackageen.

Työskentely erissä:
  Kuvia ja GPX-lokeja voi lisätä useassa ajossa. Kuvanumerointi jatkuu siitä
  mihin edellinen ajo jäi, ja GeoJSON rakennetaan aina koko kuvat/-kansiosta.
  Jo käsitellyt lähdekuvat kirjataan data/kasitellyt.json:iin, joten sama kuva
  ei kopioidu kahdesti vaikka se olisi mukana useammassa ajossa.
  GPX-lokeja voi antaa monta (tai kansion) — pisteet yhdistetään aikajärjestykseen,
  eikä pitkien aukkojen (loggeri pois päältä) yli interpoloida.

Vaatimukset:
  pip install geopandas pillow pyproj gpxpy piexif pandas requests
  pip install google-api-python-client google-auth google-auth-oauthlib
  pip install tzdata   # vain Windows, zoneinfo-kirjaston aikavyöhyketietokanta

Google-kirjautuminen (kertaluonteinen, tarvitaan Sheetien luontiin):
  python3 auth_pipeline.py

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
    import pandas as pd
    import piexif
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, TAGS
    from pyproj import Transformer
except ImportError as e:
    print(f"VIRHE: Kirjasto puuttuu: {e}")
    print("Asenna: pip install geopandas pillow pyproj gpxpy piexif pandas")
    input("\nPaina Enter sulkeaksesi...")
    raise SystemExit(1)


# ══════════════════════════════════════════════════════════════════
#  KONFIGURAATIO — muuta PROJEKTI ja REPO_POLKU tarpeen mukaan
# ══════════════════════════════════════════════════════════════════

REPO_POLKU    = Path("/home/markus/omat-apit/rak_kult_kuvakarttajulkaisu")  # Windows: Path(r"C:\GIS\maasto")
GITHUB_USER   = "MarkusHytonenPD"
GITHUB_REPO   = "maasto"
GITHUB_BRANCH = "main"
TUNNUS_SARAKE        = "tunnus"
LUOKITUS_SARAKE      = "potentiaali"    # kenttätiimin luokitus GeoPackagessa
LUOKITUS_VIR_SARAKE  = "luokitus_vir"   # viranomaisen luokitus
KOMMENTTI_VIR_SARAKE = "kommentti_vir"  # viranomaisen kommentti
NIMI_VIR_SARAKE      = "nimi_vir"       # viranomaisen nimi
VIRASTO_VIR_SARAKE   = "virasto_vir"    # viranomaisen virasto

# Viranomaistahot. Kolme kommentoijatahoa kirjaa saman kohteen toisistaan
# riippumatta, joten Sheetissä on yksi rivi per (tunnus, taho) ja
# GeoPackagessa omat sarakkeet per taho. Näin eriäviä kommentteja ei tarvitse
# sovittaa yhteen sääntöä keksimällä eikä tieto katoa.
#   avain = sarakepääte, nimi = Sheetin taho-arvo ja karttasovelluksen teksti
TAHOT = [
    {"avain": "lvv",    "nimi": "LVV"},
    {"avain": "museo",  "nimi": "Vastuumuseo"},
    {"avain": "liitto", "nimi": "Maakuntaliitto"},
]
TAHO_SARAKE = "taho"

# Sheetin kommenttikentät (pitkä muoto: yksi rivi per taho)
SHEET_VIR_KENTAT = [LUOKITUS_VIR_SARAKE, KOMMENTTI_VIR_SARAKE, NIMI_VIR_SARAKE]


def taho_sarake(kentta: str, avain: str) -> str:
    """GeoPackagen tahokohtainen sarake: ("luokitus", "lvv") → "luokitus_lvv"."""
    return f"{kentta}_{avain}"


# Viranomaissarakkeet luodaan tyhjinä GeoJSON-vientiin jos ne puuttuvat.
# Lähde-GeoPackageen niitä EI kirjoiteta pipeline-ajossa — se tehdään vasta
# tilassa 3 (Päivitä luokitukset GeoPackageen), jossa käyttäjä valitsee
# tallennetaanko päälle vai uudella nimellä.
VIRANOMAIS_SARAKKEET = [
    taho_sarake(kentta, taho["avain"])
    for taho in TAHOT
    for kentta in ("luokitus", "kommentti", "nimi")
]

KUVA_SARAKKEET = ["kuva1", "kuva2", "kuva3"]

# Nämä viedään GeoJSONiin aina, riippumatta naytettavat_sarakkeet-valinnasta.
# Puuttuvat luodaan tyhjänä merkkijonona.
PAKOLLISET_SARAKKEET = [TUNNUS_SARAKE, LUOKITUS_SARAKE] + VIRANOMAIS_SARAKKEET + KUVA_SARAKKEET

# Google Drive -kansio johon projektikohtaiset Sheetit luodaan
DRIVE_KANSIO_ID = "1Q03U_D9tsMes94fDYWydJdTV7PD9W8W4"

# Sheetin välilehti nimetään eksplisiittisesti: oletusnimi vaihtelee kielen
# mukaan (Sheet1 / Taulukko1), ja tilan 3 CSV-haku tarvitsee tarkan nimen.
SHEET_VALILEHTI = "Lausunnot"
SHEET_OTSIKOT   = [TUNNUS_SARAKE, TAHO_SARAKE] + SHEET_VIR_KENTAT

# Service account omistaa luomansa Sheetin. Ilman kirjoitusoikeutta näihin
# osoitteisiin Sheettiä ei pääse avaamaan Drivessä eikä Apps Scriptiä
# liittämään. Molemmat mukana, koska Drive-kansion omistaja on työosoite.
SHEET_JAKO_EMAILIT = [
    "markushytonen.tyo@gmail.com",
    "mark.hytonen@gmail.com",
]

# drive.file riittää kaikkeen: Sheetin luonti kansioon, välilehden ja
# otsikoiden kirjoitus Sheets APIlla sekä oikeuksien anto omalle tiedostolle.
GOOGLE_SCOPET = ["https://www.googleapis.com/auth/drive.file"]

APPS_SCRIPT_TIEDOSTO = "viranomainen_apps_script.gs"

# Google-tunnistus: OAuth-käyttäjätunnistus, EI service accountia.
# Service accountilla ei ole omaa Drive-tallennustilaa, joten se ei voi omistaa
# tiedostoja — luonti kaatuu virheeseen "The user's Drive storage quota has been
# exceeded" myös jaetussa kansiossa. Token luodaan kertaluonteisesti ajamalla
# auth_pipeline.py; kirjautunut tili omistaa luodut Sheetit.
OAUTH_CLIENT = REPO_POLKU / "credentials" / "oauth_client.json"
OAUTH_TOKEN  = REPO_POLKU / "credentials" / "drive_token.json"

# Projektikohtaiset arvot sheets_id ja apps_script_url tallennetaan projektin
# config.json:iin: sheets_id automaattisesti Sheetin luonnin yhteydessä,
# apps_script_url käsin Apps Script -deployauksen jälkeen.

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
#  VAIHE 2b — KUVIEN LIITOS GEOPACKAGEN VIITTAUKSISTA
# ══════════════════════════════════════════════════════════════════

def _dcim_nimi(arvo) -> str | None:
    """GeoPackagen kuva-arvo 'DCIM/JPEG_x.jpg' → 'jpeg_x.jpg'. Tyhjä → None."""
    if not isinstance(arvo, str) or not arvo.strip():
        return None
    return arvo.strip().replace("\\", "/").split("/")[-1].lower()


def liita_kuvat_gpkg(kuvakansio: Path, gdf) -> dict:
    """
    Liittää kuvat GeoPackagen kuva1..3-sarakkeiden perusteella.

    Kenttäsovellus kirjaa kuvaviittauksen suoraan inventointiin, joten se on
    tarkempi lähde kuin EXIF-GPS: järjestelmäkameran kuvat geotägätään GPX-
    jäljestä, ja kellodrifti siirtää pisteitä jäljen suuntaan jopa kilometrejä.
    GPS-liitos (nimeä_kuvat) on siksi vaihtoehto, ei oletus.

    Kohteen kuvasarja muodostetaan järjestyksessä:
      1. GeoPackagen kuva1..3 sen omassa järjestyksessä
      2. kansiossa jo olevat kuvat joita GeoPackage ei mainitse
    ja katkaistaan kolmeen, koska kartta näyttää enintään kolme kuvaa.
    Näin kenttäkirjaus voittaa aina, mutta GPS:n liittämiä kuvia ei hukata
    turhaan — ne täyttävät jäljelle jäävät paikat.

    Palauttaa tilastot {ok, siirretty, poistettu, ohitettu, taynna, duplikaatti}.
    """
    print("\n--- Vaihe 2: Kuvien liitos GeoPackagen viittauksista ---")
    KUVA_POLKU.mkdir(parents=True, exist_ok=True)

    lahteet = {p.name.lower(): p for p in kuvakansio.rglob("*") if p.is_file()}
    print(f"  Lähdekansiossa {len(lahteet)} tiedostoa: {kuvakansio}")

    kasitellyt = _lue_kasitellyt()
    # kohdetiedosto → lähdekuvan nimi, jotta tiedetään mistä nykyiset ovat
    lahde_per_kohde = {t["kohde"]: a.split("|")[0] for a, t in kasitellyt.items()}

    def _avain(lahde_nimi: str) -> str:
        """Kirjanpidon avain: vanha jos on, muuten lasketaan lähdetiedostosta."""
        vanha = next((a for a in kasitellyt if a.split("|")[0] == lahde_nimi), None)
        if vanha:
            return vanha
        polku = lahteet.get(lahde_nimi)
        return _kuva_avain(polku) if polku else lahde_nimi

    ok = siirretty = poistettu = ohitettu = taynna = duplikaatti = 0

    for _, rivi in gdf.iterrows():
        tunnus = _normalisoi_tunnus(rivi[TUNNUS_SARAKE])
        if not tunnus:
            continue

        gpkg_lista = [n for n in (_dcim_nimi(rivi.get(s)) for s in KUVA_SARAKKEET) if n]

        # Kansiossa olevat kuvat nykyisessä paikkajärjestyksessä
        nykyiset = []
        for n in range(1, 4):
            tiedosto = KUVA_POLKU / f"ky_{tunnus}_kuva{n}.jpg"
            if tiedosto.exists():
                nykyiset.append((tiedosto.name, lahde_per_kohde.get(tiedosto.name)))
        if not gpkg_lista and not nykyiset:
            continue

        # Haluttu järjestys: GeoPackage ensin, sitten muut kansiossa olevat
        haluttu = list(gpkg_lista)
        for nimi, lahde in nykyiset:
            if lahde and lahde not in haluttu:
                haluttu.append(lahde)
            elif not lahde:
                # Kirjanpidosta puuttuva kuva: säilytetään omana merkintänään
                haluttu.append(f"?{nimi}")
        yli = haluttu[3:]
        haluttu = haluttu[:3]
        taynna += len([x for x in yli if x in gpkg_lista])

        puuttuvat = [n for n in haluttu
                     if n in gpkg_lista and n not in lahteet
                     and n not in [l for _, l in nykyiset]]
        if puuttuvat:
            for n in puuttuvat:
                print(f"  ✗ tunnus {tunnus}: {n} ei löydy lähdekansiosta — ohitetaan")
                ohitettu += 1
            haluttu = [n for n in haluttu if n not in puuttuvat]

        nykyinen_jarjestys = [l if l else f"?{nimi}" for nimi, l in nykyiset]
        if nykyinen_jarjestys == haluttu:
            duplikaatti += len(haluttu)
            continue

        # Väliaikaisnimet ensin, jottei uudelleennimeäminen törmää itseensä
        tilapaiset, alkuperainen = {}, {}
        for i, (nimi, lahde) in enumerate(nykyiset, start=1):
            tunniste = lahde if lahde else f"?{nimi}"
            tilapainen = KUVA_POLKU / f"ky_{tunnus}_siirto{i}.jpg"
            (KUVA_POLKU / nimi).rename(tilapainen)
            tilapaiset[tunniste]   = tilapainen
            alkuperainen[tunniste] = nimi

        for i, tunniste in enumerate(haluttu, start=1):
            kohde = KUVA_POLKU / f"ky_{tunnus}_kuva{i}.jpg"
            if tunniste in tilapaiset:
                tilapaiset.pop(tunniste).rename(kohde)
                if alkuperainen[tunniste] != kohde.name:
                    print(f"  ~ tunnus {tunnus}: {alkuperainen[tunniste]} → {kohde.name}")
                    siirretty += 1
            else:
                shutil.copy2(lahteet[tunniste], kohde)
                print(f"  + tunnus {tunnus}: {tunniste} → {kohde.name}")
                ok += 1
            if not tunniste.startswith("?"):
                _merkitse_kasitellyksi(kasitellyt, _avain(tunniste), kohde.name, tunnus)

        # Paikkansa menettäneet: GeoPackage ei mainitse eikä tilaa jäänyt
        for tunniste, tilapainen in tilapaiset.items():
            print(f"  − tunnus {tunnus}: {tilapainen.name} poistuu "
                  f"(paikat täyttyivät GeoPackagen kuvilla)")
            tilapainen.unlink()
            poistettu += 1
            avain = next((a for a in kasitellyt if a.split("|")[0] == tunniste), None)
            if avain:
                kasitellyt.pop(avain)

    _kirjoita_kasitellyt(kasitellyt)
    print(f"  Kopioitu: {ok}, siirretty paikkaa: {siirretty}, poistettu: {poistettu}, "
          f"ennallaan: {duplikaatti}, ei tilaa: {taynna}, ei löytynyt: {ohitettu}")
    return {"ok": ok, "siirretty": siirretty, "poistettu": poistettu,
            "ohitettu": ohitettu, "taynna": taynna, "duplikaatti": duplikaatti}


# ══════════════════════════════════════════════════════════════════
#  VAIHE 3 & 4b — GIT PUSH
# ══════════════════════════════════════════════════════════════════

def git_push(viesti: str, *suhteelliset_polut: str):
    """git add → commit → push. Ohittaa push:n jos ei muutoksia."""
    polut = [p for p in suhteelliset_polut if p]
    print(f"  git add {' '.join(polut)}")
    subprocess.run(
        ["git", "-C", str(REPO_POLKU), "add", *polut],
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


def _tulosta_luokitusarvot(gdf):
    """
    Tulostaa mitkä arvot LUOKITUS_SARAKE-sarakkeessa esiintyy ja montako
    kohdetta kullakin on. Sarake voi puuttua kokonaan (uusi aineisto) —
    silloin siitä vain huomautetaan.
    """
    if LUOKITUS_SARAKE not in gdf.columns:
        print(f"  Kenttäluokitusarvot: sarake '{LUOKITUS_SARAKE}' puuttuu GeoPackagesta")
        return

    sarja = gdf[LUOKITUS_SARAKE]
    tyhja = sarja.isna() | (sarja.astype(str).str.strip() == "")
    laskurit = sarja[~tyhja].astype(str).str.strip().value_counts()

    osat = [f"{arvo} ({maara})" for arvo, maara in sorted(laskurit.items())]
    if tyhja.any():
        osat.append(f"tyhjä ({int(tyhja.sum())})")
    print(f"  Kenttäluokitusarvot ('{LUOKITUS_SARAKE}'): " + (", ".join(osat) or "ei yhtään"))


def _varmista_sarakkeet(gdf, sarakkeet: list[str]):
    """Luo puuttuvat sarakkeet tyhjänä merkkijonona (= Ei merkintää)."""
    puuttuvat = [s for s in sarakkeet if s not in gdf.columns]
    for sarake in puuttuvat:
        gdf[sarake] = ""
    if puuttuvat:
        print(f"  Luotu tyhjät sarakkeet: {', '.join(puuttuvat)}")
    return gdf


def _rajaa_sarakkeet(gdf, naytettavat: list[str]):
    """
    Jättää GeoJSONiin vain valitut ja pakolliset sarakkeet.
    Järjestys: käyttäjän valinta ensin (= popupin rivijärjestys),
    sitten loput pakolliset, viimeisenä geometria.
    """
    geom = gdf.geometry.name
    jarjestys: list[str] = []
    for sarake in list(naytettavat) + PAKOLLISET_SARAKKEET:
        if sarake != geom and sarake in gdf.columns and sarake not in jarjestys:
            jarjestys.append(sarake)
    pudotettu = [c for c in gdf.columns if c not in jarjestys and c != geom]
    if pudotettu:
        print(f"  Ei viedä ({len(pudotettu)}): {', '.join(pudotettu)}")
    return gdf[jarjestys + [geom]]


def vie_geojson(gpkg_polku: Path, layer_nimi: str) -> dict:
    """
    Vaihe 4: lukee GeoPackagen, lisää kuva1/2/3-URL:t, vie GeoJSON WGS84:ssä.
    Vietävät sarakkeet = config.json:in naytettavat_sarakkeet + pakolliset.
    Palauttaa tilastot {rakennuksia, kuvilla}.
    """
    print("\n--- Vaihe 4: GeoJSON-vienti ---")
    DATA_POLKU.mkdir(parents=True, exist_ok=True)

    gdf = _lue_ja_normalisoi_crs(gpkg_polku, layer_nimi, "EPSG:4326")
    _tulosta_luokitusarvot(gdf)
    gdf = _varmista_sarakkeet(gdf, PAKOLLISET_SARAKKEET)

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

    gdf = _rajaa_sarakkeet(gdf, _lue_projekticonfig().get("naytettavat_sarakkeet") or [])

    kohde = DATA_POLKU / "kohteet.geojson"
    gdf.to_file(kohde, driver="GeoJSON")
    print(f"  Viety: {kohde}")

    kuvilla = sum(1 for t in gdf[TUNNUS_SARAKE] if t in kuva_map)
    print(f"  {len(gdf)} rakennusta, {kuvilla} sai kuvan")
    return {"rakennuksia": len(gdf), "kuvilla": kuvilla}


# ══════════════════════════════════════════════════════════════════
#  PROJEKTICONFIG
# ══════════════════════════════════════════════════════════════════

def _config_polku() -> Path:
    return PROJEKTI_POLKU / "config.json"


def _docs_polku() -> Path:
    return REPO_POLKU / "docs" / PROJEKTI


def kopioi_docsiin() -> list:
    """
    Kopioi config.json:in ja kohteet.geojsonin docs/[projekti]/:iin ja
    palauttaa git add:iin annettavat suhteelliset polut.

    Kartta lukee datan ensisijaisesti GitHub Pagesista, koska Pages
    tyhjentää välimuistinsa deployn yhteydessä. Sama tiedosto
    raw.githubusercontent.comista tarjoillaan max-age=300 -otsakkeella,
    eikä sen CDN revalidoi pyynnöstä — sitä kautta tämän ajon tulokset
    näkyisivät kartalla enintään viiden minuutin viiveellä.
    """
    docs = _docs_polku()
    (docs / "data").mkdir(parents=True, exist_ok=True)

    polut = []
    for lahde, kohde in (
        (_config_polku(),                docs / "config.json"),
        (DATA_POLKU / "kohteet.geojson", docs / "data" / "kohteet.geojson"),
    ):
        if not lahde.is_file():
            continue
        shutil.copy2(lahde, kohde)
        suhteellinen = kohde.relative_to(REPO_POLKU).as_posix()
        polut.append(suhteellinen)
        print(f"  Kopioitu karttasovellukseen: {suhteellinen}")
    return polut


def _lue_projekticonfig() -> dict:
    """Lukee projektin config.json:in. Palauttaa {} jos tiedostoa ei ole."""
    polku = _config_polku()
    if not polku.exists():
        return {}
    try:
        return json.loads(polku.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ config.json ei aukea ({e}) — käsitellään tyhjänä")
        return {}


def _kirjoita_projekticonfig(cfg: dict):
    """
    Kirjoittaa koko configin. Kutsujan on luettava config ensin
    _lue_projekticonfig():lla, jotta muut avaimet (nimi, tasot,
    sheets_id, apps_script_url) säilyvät.
    """
    PROJEKTI_POLKU.mkdir(parents=True, exist_ok=True)
    _config_polku().write_text(
        json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8"
    )


def alusta_projekticonfig():
    """Luo config.json-pohjan ja docs/[projekti]/index.html jos niitä ei vielä ole."""
    PROJEKTI_POLKU.mkdir(parents=True, exist_ok=True)

    if not _config_polku().exists():
        _kirjoita_projekticonfig({"nimi": PROJEKTI, "tasot": []})
        print(f"  Luotu: {_config_polku()}  (lisää WMS-tasot tähän tarvittaessa)")

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
#  VIRANOMAISLAUSUNTOJEN GOOGLE SHEET
# ══════════════════════════════════════════════════════════════════

def _google_creds():
    """
    Palauttaa OAuth-tunnisteet credentials/drive_token.json:ista, tai None
    jos kirjautumista ei ole tehty. Vanhentunut access token uusitaan
    refresh tokenilla ja tallennetaan takaisin tiedostoon.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not OAUTH_TOKEN.is_file():
        print(f"  ⚠ Google-kirjautumista ei ole tehty ({OAUTH_TOKEN} puuttuu)")
        print("    Aja kertaluonteisesti: python3 auth_pipeline.py")
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN), GOOGLE_SCOPET)
    except Exception as e:
        print(f"  ⚠ Tokenia ei voitu lukea ({e})")
        print("    Aja uudelleen: python3 auth_pipeline.py")
        return None

    if creds.valid:
        return creds

    if not creds.refresh_token:
        print("  ⚠ Token on vanhentunut eikä sisällä refresh tokenia")
        print("    Aja uudelleen: python3 auth_pipeline.py")
        return None

    try:
        creds.refresh(Request())
        OAUTH_TOKEN.write_text(creds.to_json(), encoding="utf-8")
        return creds
    except Exception as e:
        print(f"  ⚠ Tokenin uusinta epäonnistui ({e})")
        print("    Aja uudelleen: python3 auth_pipeline.py")
        return None


def _aseta_julkinen_lukuoikeus(drive, tiedosto_id: str):
    """
    Varmistaa että linkin tietävät saavat VAIN lukuoikeuden.

    Drive-kansiosta periytyy uusiin tiedostoihin sen oma jakoasetus. Jos
    kohdekansio on jaettu linkillä muokkausoikeudella, Google EI salli
    perityn oikeuden laskemista tiedostotasolla — silloin kuka tahansa linkin
    tietävä voisi kirjoittaa kommentteja suoraan Sheetiin ohi Apps Script
    -endpointin. Sitä ei voi korjata koodista, joten siitä varoitetaan.
    """
    for perm in drive.permissions().list(
        fileId=tiedosto_id, fields="permissions(id,type,role)"
    ).execute().get("permissions", []):
        if perm["type"] == "anyone":
            if perm["role"] == "reader":
                return
            try:
                drive.permissions().update(
                    fileId=tiedosto_id, permissionId=perm["id"], body={"role": "reader"}
                ).execute()
                print(f"  Peritty julkinen oikeus laskettu: {perm['role']} → reader")
            except Exception:
                print(f"  ⚠ HUOM: linkin tietävillä on '{perm['role']}'-oikeus, ei lukuoikeutta.")
                print(f"    Oikeus periytyy Drive-kansiosta {DRIVE_KANSIO_ID}, eikä sitä voi")
                print("    laskea tiedostotasolla. Kuka tahansa linkin tietävä voi siis")
                print("    muokata kommentteja suoraan Sheetissä.")
                print("    Korjaus: avaa kansio Drivessä → Jaa → vaihda linkkijako")
                print("    'Rajoitettu'-tilaan. Pipeline antaa lukuoikeuden per Sheet.")
            return
    drive.permissions().create(
        fileId=tiedosto_id, body={"type": "anyone", "role": "reader"}
    ).execute()


def _julkinen_rooli(drive, tiedosto_id: str) -> str:
    """Tarkistuslukema: mikä oikeus linkin tietävillä lopulta on."""
    for perm in drive.permissions().list(
        fileId=tiedosto_id, fields="permissions(type,role)"
    ).execute().get("permissions", []):
        if perm["type"] == "anyone":
            return perm["role"]
    return "ei julkista oikeutta"


def _tulosta_deployausohje(sheets_url: str):
    print("\n  SEURAAVA VAIHE — Apps Script -endpoint (tehdään kerran per projekti):")
    print(f"    1. Avaa Sheet: {sheets_url}")
    print("    2. Laajennukset → Apps Script")
    print(f"    3. Kopioi {APPS_SCRIPT_TIEDOSTO} editoriin ja tallenna")
    print("    4. Ota käyttöön → Uusi deployment → Tyyppi: Web-sovellus")
    print("       Suorittaja: Minä  |  Käyttäjät: Kaikki")
    print("    5. Kopioi Web app URL ja lisää se projektin config.json:iin")
    print('       avaimeen "apps_script_url"')


def luo_projekti_sheet(projekti: str) -> str | None:
    """
    Luo projektikohtaisen Google Sheetin viranomaisten kommenteille:
    otsikkorivi, julkinen lukuoikeus (CSV-haku ilman autentikointia) ja
    kirjoitusoikeus SHEET_JAKO_EMAIL:lle. Tallentaa sheets_id:n config.json:iin.

    Palauttaa Sheetin ID:n, tai None jos luonti ei onnistunut — pipeline
    jatkaa silloin normaalisti, Sheet voidaan luoda seuraavalla ajolla.
    """
    print("\n--- Viranomaisten kommenttien Google Sheet ---")

    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        print(f"  ⚠ Kirjasto puuttuu ({e}) — Sheetiä ei luotu")
        print("    Asenna: pip install --user google-api-python-client google-auth")
        return None

    creds = _google_creds()
    if creds is None:
        print("    Pipeline jatkaa — Sheet voidaan luoda seuraavalla ajolla.")
        return None

    nimi = f"Viranomaiskommentit_{projekti}"
    try:
        drive  = build("drive",  "v3", credentials=creds, cache_discovery=False)
        sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

        # 1) Sheet luodaan Drive APIlla suoraan oikeaan kansioon
        sheets_id = drive.files().create(
            body={
                "name":     nimi,
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents":  [DRIVE_KANSIO_ID],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()["id"]

        # 2) Välilehden nimi, kiinteä otsikkorivi ja otsikot
        meta   = sheets.spreadsheets().get(spreadsheetId=sheets_id).execute()
        vali_id = meta["sheets"][0]["properties"]["sheetId"]
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheets_id,
            body={"requests": [
                {"updateSheetProperties": {
                    "properties": {
                        "sheetId":        vali_id,
                        "title":          SHEET_VALILEHTI,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "title,gridProperties.frozenRowCount",
                }},
                {"repeatCell": {
                    "range": {"sheetId": vali_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell":  {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }},
            ]},
        ).execute()
        sheets.spreadsheets().values().update(
            spreadsheetId=sheets_id,
            range=f"{SHEET_VALILEHTI}!A1",
            valueInputOption="RAW",
            body={"values": [SHEET_OTSIKOT]},
        ).execute()

        # 3) Oikeudet: julkinen luku (CSV-haku) + oma kirjoitusoikeus
        _aseta_julkinen_lukuoikeus(drive, sheets_id)
        for email in SHEET_JAKO_EMAILIT:
            try:
                drive.permissions().create(
                    fileId=sheets_id,
                    body={"type": "user", "role": "writer", "emailAddress": email},
                    sendNotificationEmail=False,
                ).execute()
            except Exception as e:
                # Yhden osoitteen epäonnistuminen ei kaada luontia
                print(f"  ⚠ Kirjoitusoikeutta ei voitu antaa osoitteelle {email}: {e}")

    except Exception as e:
        print(f"  ⚠ Sheetin luonti epäonnistui: {e}")
        print("    Tarkista että:")
        print(f"      • kirjautuneella tilillä on kirjoitusoikeus Drive-kansioon {DRIVE_KANSIO_ID}")
        print("      • Drive API ja Sheets API ovat päällä projektissa gws-sheets-494810")
        print("    Kirjautumisen voi uusia: python3 auth_pipeline.py")
        print("    Pipeline jatkaa — Sheet voidaan luoda seuraavalla ajolla.")
        return None

    cfg = _lue_projekticonfig()
    cfg["sheets_id"]        = sheets_id
    cfg["sheets_valilehti"] = SHEET_VALILEHTI
    cfg.setdefault("apps_script_url", "")
    _kirjoita_projekticonfig(cfg)

    sheets_url = f"https://docs.google.com/spreadsheets/d/{sheets_id}/edit"
    print(f"  ✓ Luotu: {nimi}")
    print(f"    {sheets_url}")
    print(f"    Välilehti: {SHEET_VALILEHTI}  |  Otsikot: {', '.join(SHEET_OTSIKOT)}")
    print(f"    Linkin tietävät: {_julkinen_rooli(drive, sheets_id)}"
          f"  |  Kirjoitusoikeus: {', '.join(SHEET_JAKO_EMAILIT)}")
    print("    sheets_id tallennettu config.json:iin")
    _tulosta_deployausohje(sheets_url)
    return sheets_id


# ══════════════════════════════════════════════════════════════════
#  NÄYTETTÄVIEN SARAKKEIDEN VALINTA
# ══════════════════════════════════════════════════════════════════

def _esimerkkiarvo(sarja) -> str:
    """Ensimmäinen ei-tyhjä arvo esimerkkinä. Tyhjästä sarakkeesta '—'."""
    for arvo in sarja:
        if arvo is None:
            continue
        try:
            if pd.isna(arvo):      # NaN, NaT, pd.NA
                continue
        except (TypeError, ValueError):
            pass
        teksti = str(arvo).strip()
        if not teksti or teksti.lower() in ("nan", "nat", "none"):
            continue
        if len(teksti) > 40:
            teksti = teksti[:37] + "..."
        return f'esim. "{teksti}"'
    return "—"


def kysy_naytettavat_sarakkeet(gdf) -> list[str]:
    """
    Kysyy mitkä GeoPackagen sarakkeet näytetään selaimessa kohteen popupissa.
    Palauttaa sarakenimet käyttäjän antamassa järjestyksessä (= popupin
    rivijärjestys) ja tallentaa valinnan config.json:iin.

    Kuva- ja viranomaissarakkeet jätetään listasta pois — ne ovat pakollisia
    ja karttasovellus esittää ne omissa osioissaan.
    """
    ohita     = set(VIRANOMAIS_SARAKKEET) | set(KUVA_SARAKKEET) | {gdf.geometry.name}
    valittavat = [c for c in gdf.columns if c not in ohita]
    if not valittavat:
        return []

    print("\nSaatavilla olevat sarakkeet:")
    leveys = max(len(c) for c in valittavat)
    numero_leveys = len(str(len(valittavat) - 1))
    for i, sarake in enumerate(valittavat):
        numero = f"[{i}]".rjust(numero_leveys + 2)
        print(f"  {numero} {sarake.ljust(leveys)}  ({_esimerkkiarvo(gdf[sarake])})")

    cfg      = _lue_projekticonfig()
    tallessa = cfg.get("naytettavat_sarakkeet") or []
    aiempi   = [c for c in tallessa if c in valittavat]
    kadonneet = [c for c in tallessa if c not in valittavat]
    if kadonneet:
        print(f"\n  ⚠ Aiemmin valittu, ei löydy tästä aineistosta: {', '.join(kadonneet)}")
    if aiempi:
        print(f"\nNykyinen valinta: {', '.join(aiempi)}")

    oletus_teksti = "nykyinen valinta" if aiempi else "kaikki"
    nimi_avain    = {c.lower(): c for c in valittavat}

    while True:
        syote = input(
            f"\nValitse näytettävät sarakkeet (pilkulla erotetut numerot tai nimet, "
            f"Enter = {oletus_teksti}):\n> "
        ).strip()

        if not syote:
            valinta = aiempi or list(valittavat)
            break

        valinta, tuntemattomat = [], []
        for osa in (o.strip() for o in syote.split(",")):
            if not osa:
                continue
            if osa.isdigit() and int(osa) < len(valittavat):
                sarake = valittavat[int(osa)]
            else:
                sarake = nimi_avain.get(osa.lower())
            if sarake is None:
                tuntemattomat.append(osa)
            elif sarake not in valinta:
                valinta.append(sarake)

        if tuntemattomat:
            print(f"  ⚠ Ei tunnistettu: {', '.join(tuntemattomat)} — yritä uudelleen")
            continue
        if not valinta:
            print("  ⚠ Valitse vähintään yksi sarake")
            continue
        break

    cfg["naytettavat_sarakkeet"] = valinta
    _kirjoita_projekticonfig(cfg)
    print(f"  Näytettävät sarakkeet: {', '.join(valinta)}")
    return valinta


# ══════════════════════════════════════════════════════════════════
#  TILA 3 — LUOKITUSTEN PÄIVITYS GEOPACKAGEEN
# ══════════════════════════════════════════════════════════════════

def _normalisoi_tunnus(arvo) -> str:
    """
    Tunnus vertailukelpoiseen muotoon. GeoPackagessa se voi olla teksti,
    kokonaisluku tai liukuluku (63 / '63' / 63.0) — kaikki tarkoittavat samaa.
    """
    if arvo is None:
        return ""
    if isinstance(arvo, float):
        if pd.isna(arvo):
            return ""
        if arvo.is_integer():
            return str(int(arvo))
    teksti = str(arvo).strip()
    if teksti.endswith(".0") and teksti[:-2].lstrip("-").isdigit():
        return teksti[:-2]
    return teksti


def _pura_gpkg_geometria(blob):
    """
    Purkaa GeoPackagen geometriablobin otsikon (GPKG-spec 2.1.3).
    Palauttaa (tyhja, envelope, wkb), jossa envelope = (minx, maxx, miny, maxy).
    """
    import struct

    if blob is None:
        return True, None, None
    if isinstance(blob, str):
        blob = blob.encode("latin-1", "ignore")
    blob = bytes(blob)
    if len(blob) < 8 or blob[0:2] != b"GP":
        return False, None, blob            # ei GPKG-otsikkoa — oletetaan paljas WKB

    liput  = blob[3]
    pikku  = bool(liput & 0x01)             # tavujärjestys
    tyhja  = bool(liput & 0x10)             # empty geometry flag
    koot   = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    pituus = koot.get((liput >> 1) & 0x07)
    if pituus is None:
        return tyhja, None, None

    loppu = 8 + pituus
    env   = None
    if pituus:
        arvot = struct.unpack(("<" if pikku else ">") + "d" * (pituus // 8),
                              blob[8:loppu])
        env = (arvot[0], arvot[1], arvot[2], arvot[3])
    return tyhja, env, blob[loppu:]


def _gpkg_rajat(blob):
    """(minx, maxx, miny, maxy) tai None. Käyttää otsikon envelopea jos on."""
    tyhja, env, wkb = _pura_gpkg_geometria(blob)
    if tyhja:
        return None
    if env:
        return env
    if not wkb:
        return None
    try:
        from shapely import wkb as shapely_wkb
        minx, miny, maxx, maxy = shapely_wkb.loads(wkb).bounds
        return (minx, maxx, miny, maxy)
    except Exception:
        return None


def _rekisteroi_gpkg_funktiot(yhteys):
    """
    GeoPackagen RTree-triggerit kutsuvat ST_*-funktioita, jotka tulevat
    normaalisti GDAL:sta — paljas sqlite3 ei tunne niitä. Triggerit
    rtree_*_update4 ja _update5 laukeavat MINKÄ TAHANSA sarakkeen
    päivityksestä ja kutsuvat ST_IsEmpty:ä jo WHEN-ehdossaan, joten ilman
    näitä pelkkä attribuuttipäivitys kaatuu virheeseen
    "no such function: ST_IsEmpty".
    """
    yhteys.create_function(
        "ST_IsEmpty", 1, lambda b: 1 if _pura_gpkg_geometria(b)[0] else 0)
    for nimi, indeksi in (("ST_MinX", 0), ("ST_MaxX", 1), ("ST_MinY", 2), ("ST_MaxY", 3)):
        yhteys.create_function(
            nimi, 1,
            lambda b, i=indeksi: (_gpkg_rajat(b) or (None, None, None, None))[i])


def lue_kaavoittajan_geojson(polku: Path) -> dict:
    """
    Lukee karttasovelluksen "Lataa kaavoittajan suositukset" -tiedoston.
    Palauttaa {tunnus: luokitusarvo}.
    """
    try:
        data = json.loads(polku.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ GeoJSONia ei voitu lukea: {e}")
        return {}

    tulos = {}
    for piirre in data.get("features", []):
        ominaisuudet = piirre.get("properties") or {}
        tunnus = _normalisoi_tunnus(ominaisuudet.get(TUNNUS_SARAKE))
        if not tunnus or LUOKITUS_SARAKE not in ominaisuudet:
            continue
        arvo = ominaisuudet[LUOKITUS_SARAKE]
        tulos[tunnus] = "" if arvo is None else str(arvo)

    print(f"  Kaavoittajan GeoJSON: {len(tulos)} kohdetta")
    return tulos


def _lue_sheet_apilla(sheets_id: str, valilehti: str):
    """Lukee välilehden Sheets-API:lla. Palauttaa DataFramen tai None."""
    creds = _google_creds()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build

        palvelu = build("sheets", "v4", credentials=creds, cache_discovery=False)
        arvot = (palvelu.spreadsheets().values()
                 .get(spreadsheetId=sheets_id, range=valilehti)
                 .execute().get("values", []))
    except Exception as e:
        print(f"  ⚠ Sheets-API-luku epäonnistui ({e}) — yritetään julkista CSV:tä")
        return None

    if not arvot:
        print(f"  ⚠ Välilehti '{valilehti}' on tyhjä")
        return pd.DataFrame()

    otsikot = [str(x).strip() for x in arvot[0]]
    # Vajaat rivit täytetään, jotta DataFrame syntyy myös kun loppusarakkeet
    # ovat tyhjiä — Sheets-API katkaisee rivin viimeiseen täytettyyn soluun
    rivit = [(r + [""] * len(otsikot))[:len(otsikot)] for r in arvot[1:]]
    return pd.DataFrame(rivit, columns=otsikot, dtype=str)


def _lue_sheet_csvna(sheets_id: str, valilehti: str):
    """Varalla: julkinen gviz-CSV. Toimii vain jos Sheet on jaettu linkillä."""
    try:
        import io
        from urllib.parse import quote

        import requests
    except ImportError as e:
        print(f"  ⚠ Kirjasto puuttuu ({e}) — viranomaisdataa ei haettu")
        return None

    url = (f"https://docs.google.com/spreadsheets/d/{sheets_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(valilehti)}")
    try:
        vastaus = requests.get(url, timeout=30)
        vastaus.raise_for_status()
        vastaus.encoding = "utf-8"
        return pd.read_csv(io.StringIO(vastaus.text), dtype=str)
    except Exception as e:
        print(f"  ⚠ Sheets-haku epäonnistui: {e}")
        print(f"    Aja 'python3 auth_pipeline.py' tai jaa Sheet lukuoikeudella")
        return None


def hae_viranomaisdata() -> dict:
    """
    Hakee viranomaisten kommentit Sheetsistä Sheets-API:lla omalla tokenilla,
    koska Sheet on jaettu lukuoikeudella. Palauttaa {tunnus: {sarake: arvo}}.
    """
    cfg       = _lue_projekticonfig()
    sheets_id = cfg.get("sheets_id")
    if not sheets_id:
        print("  Sheets-ID:tä ei ole config.json:issa — viranomaisdataa ei haettu")
        return {}

    valilehti = cfg.get("sheets_valilehti") or SHEET_VALILEHTI

    # Luku Sheets-API:lla omalla tokenilla. Aiemmin tähän käytettiin julkista
    # gviz-CSV:tä, mutta se vaatii että Sheet on jaettu linkin tietäville —
    # ja Drive-kansio on tarkoituksella Rajoitettu-tilassa, jottei kukaan
    # pääse kirjoittamaan kommentteja endpointin ohi. API-luku toimii
    # jakoasetuksista riippumatta, koska token omistaa tiedoston.
    df = _lue_sheet_apilla(sheets_id, valilehti)
    if df is None:
        df = _lue_sheet_csvna(sheets_id, valilehti)
    if df is None:
        return {}

    # gviz ei virheile tuntemattomasta sheet-nimestä vaan palauttaa
    # ensimmäisen välilehden. Otsikkotarkistus on siis ainoa suoja väärän
    # välilehden lukemiselta — älä poista sitä.
    puuttuvat = [s for s in SHEET_OTSIKOT if s not in df.columns]
    if puuttuvat:
        print(f"  ⚠ Sheetistä puuttuu sarakkeita: {', '.join(puuttuvat)}")
        print(f"    Löytyi: {', '.join(str(c) for c in df.columns[:6])}")
        return {}

    # gviz palauttaa otsikoiden jälkeen tyhjiä sarakkeita — poimitaan nimellä
    df = df[SHEET_OTSIKOT].fillna("")

    # Sheetissä on yksi rivi per (tunnus, taho); GeoPackageen viedään
    # tahokohtaisiin sarakkeisiin, joten rivit kootaan tunnuksen alle.
    nimi_avaimeksi = {taho["nimi"]: taho["avain"] for taho in TAHOT}

    tulos: dict = {}
    kommentteja = 0
    tuntemattomat: dict = {}
    for _, rivi in df.iterrows():
        tunnus = _normalisoi_tunnus(rivi[TUNNUS_SARAKE])
        if not tunnus:
            continue
        taho_nimi = str(rivi[TAHO_SARAKE]).strip()
        avain = nimi_avaimeksi.get(taho_nimi)
        if not avain:
            # Tuntematon taho ohitetaan: tieto ei kuulu millekään sarakkeelle
            # eikä sitä saa hiljaa kirjoittaa väärän tahon päälle
            tuntemattomat[taho_nimi] = tuntemattomat.get(taho_nimi, 0) + 1
            continue
        kohde = tulos.setdefault(tunnus, {})
        for kentta, sheet_sarake in zip(("luokitus", "kommentti", "nimi"),
                                        SHEET_VIR_KENTAT):
            kohde[taho_sarake(kentta, avain)] = str(rivi[sheet_sarake]).strip()
        kommentteja += 1

    for nimi, maara in tuntemattomat.items():
        print(f"  ⚠ Ohitettu {maara} riviä tuntemattomalla taholla: {nimi!r}")
        print(f"    Sallitut: {', '.join(t['nimi'] for t in TAHOT)}")
    print(f"  Sheetsistä: {kommentteja} kommenttia {len(tulos)} kohteelle")
    return tulos


def paivita_geopackage(gpkg_polku: Path, layer_nimi: str,
                       kaava: dict, viranomais: dict) -> dict:
    """
    Päivittää luokitukset GeoPackageen SQLitellä paikan päällä.

    EI käytä gdf.to_file():ta, koska se kirjoittaisi tiedoston uudelleen ja
    pudottaisi samaan GeoPackageen tallennetut QGIS-tyylit (layer_styles) ja
    muut tasot. ALTER TABLE + UPDATE koskee vain haluttuja sarakkeita.

    Palauttaa tilastot {kaava_ok, vir_ok, puuttuvat, lisatyt_sarakkeet}.
    """
    import sqlite3

    yhteys = sqlite3.connect(str(gpkg_polku))
    try:
        _rekisteroi_gpkg_funktiot(yhteys)
        kursori = yhteys.cursor()

        taulut = [r[0] for r in kursori.execute(
            "SELECT table_name FROM gpkg_contents").fetchall()]
        if layer_nimi not in taulut:
            raise ValueError(
                f"Layeria '{layer_nimi}' ei ole GeoPackagessa. Löytyi: {', '.join(taulut)}")

        sarakkeet = [r[1] for r in kursori.execute(
            f'PRAGMA table_info("{layer_nimi}")').fetchall()]
        if TUNNUS_SARAKE not in sarakkeet:
            raise ValueError(f"Saraketta '{TUNNUS_SARAKE}' ei ole layerissa '{layer_nimi}'")

        # Puuttuvat sarakkeet lisätään tyhjinä
        lisatyt = []
        for sarake in [LUOKITUS_SARAKE] + VIRANOMAIS_SARAKKEET:
            if sarake not in sarakkeet:
                kursori.execute(f'ALTER TABLE "{layer_nimi}" ADD COLUMN "{sarake}" TEXT')
                lisatyt.append(sarake)
        if lisatyt:
            print(f"  Lisätty sarakkeet: {', '.join(lisatyt)}")

        # rowid → tunnus, jotta päivitys ei riipu tunnuksen SQL-tyypistä
        rivit = kursori.execute(
            f'SELECT rowid, "{TUNNUS_SARAKE}" FROM "{layer_nimi}"').fetchall()
        rowid_per_tunnus = {}
        for rowid, tunnus in rivit:
            normi = _normalisoi_tunnus(tunnus)
            if normi:
                rowid_per_tunnus.setdefault(normi, []).append(rowid)

        kaava_ok = vir_ok = 0
        puuttuvat = []

        for tunnus, arvo in kaava.items():
            rowidit = rowid_per_tunnus.get(tunnus)
            if not rowidit:
                puuttuvat.append(tunnus)
                continue
            for rowid in rowidit:
                kursori.execute(
                    f'UPDATE "{layer_nimi}" SET "{LUOKITUS_SARAKE}" = ? WHERE rowid = ?',
                    (arvo, rowid))
            kaava_ok += 1

        for tunnus, arvot in viranomais.items():
            rowidit = rowid_per_tunnus.get(tunnus)
            if not rowidit:
                puuttuvat.append(tunnus)
                continue
            asetukset = ", ".join(f'"{s}" = ?' for s in VIRANOMAIS_SARAKKEET)
            for rowid in rowidit:
                kursori.execute(
                    f'UPDATE "{layer_nimi}" SET {asetukset} WHERE rowid = ?',
                    [arvot.get(s, "") for s in VIRANOMAIS_SARAKKEET] + [rowid])
            vir_ok += 1

        yhteys.commit()
    finally:
        yhteys.close()

    return {
        "kaava_ok": kaava_ok,
        "vir_ok": vir_ok,
        "puuttuvat": sorted(set(puuttuvat)),
        "lisatyt_sarakkeet": lisatyt,
    }


def tila3_paivita_luokitukset(gpkg_polku: Path, layer_nimi: str) -> Path | None:
    """
    Tila 3: yhdistää kaavoittajan selainluokitukset ja viranomaisten kommentit
    GeoPackageen. Palauttaa päivitetyn GeoPackagen polun, tai None.
    """
    print("\n--- Tila 3: Päivitä luokitukset GeoPackageen ---")

    # 1) Kaavoittajan GeoJSON (valinnainen)
    kaava = {}
    syote = input(
        "\nKaavoittajan luokitus-GeoJSON (karttasovelluksen lataama tiedosto,\n"
        "Enter = ohita ja päivitä vain viranomaisdata):\n> "
    ).strip().strip('"')
    if syote:
        polku = Path(syote)
        if not polku.is_file():
            print(f"  ⚠ Tiedostoa ei löydy: {polku}")
            if input("  Jatketaanko ilman sitä? (k/e): ").strip().lower() != "k":
                return None
        else:
            kaava = lue_kaavoittajan_geojson(polku)

    # 2) Viranomaisdata Sheetsistä
    print()
    viranomais = hae_viranomaisdata()

    if not kaava and not viranomais:
        print("\n  Ei päivitettävää dataa kummastakaan lähteestä.")
        return None

    # 3) Kohdetiedosto
    print("\nTallennus:")
    print("  1 = Päälle (alkuperäinen GeoPackage)")
    print("  2 = Uudella nimellä (kopio)")
    valinta = input("Valinta (1/2): ").strip()

    kohde = gpkg_polku
    if valinta == "2":
        nimi = input(
            f"\nUusi tiedostonimi [{gpkg_polku.stem}_paivitetty.gpkg]:\n> "
        ).strip().strip('"')
        kohde = (gpkg_polku.parent / (nimi or f"{gpkg_polku.stem}_paivitetty.gpkg"))
        if kohde.suffix.lower() != ".gpkg":
            kohde = kohde.with_suffix(".gpkg")
        if kohde.exists() and input(f"  {kohde.name} on jo olemassa. Korvataanko? (k/e): "
                                   ).strip().lower() != "k":
            return None
        # Kopioidaan koko tiedosto, jotta tyylit ja muut tasot säilyvät
        shutil.copy2(gpkg_polku, kohde)
        print(f"  Kopioitu: {kohde}")
    elif valinta != "1":
        print("  Virheellinen valinta — ei tallennettu.")
        return None

    # 4) Päivitys
    print()
    try:
        tilastot = paivita_geopackage(kohde, layer_nimi, kaava, viranomais)
    except Exception as e:
        print(f"  VIRHE: päivitys epäonnistui: {e}")
        return None

    print(f"\n  Päivitetty: {kohde}")
    print(f"    Kaavoittajan luokituksia:   {tilastot['kaava_ok']}")
    print(f"    Viranomaiskommentteja:      {tilastot['vir_ok']}")
    if tilastot["puuttuvat"]:
        naytettavat = ", ".join(tilastot["puuttuvat"][:10])
        loput = len(tilastot["puuttuvat"]) - 10
        print(f"    ⚠ Tunnuksia ei löytynyt GeoPackagesta: {len(tilastot['puuttuvat'])}"
              f"  ({naytettavat}{f' ... +{loput}' if loput > 0 else ''})")
        print("      Yleisin syy: väärä projekti tai vanhentunut GeoPackage.")

    # 5) kohteet.gpkg projektikansioon
    if input("\nViedäänkö myös kohteet.gpkg projektikansioon? (k/e): ").strip().lower() == "k":
        try:
            DATA_POLKU.mkdir(parents=True, exist_ok=True)
            gdf = _lue_ja_normalisoi_crs(kohde, layer_nimi, "EPSG:3067")
            gdf.to_file(DATA_POLKU / "kohteet.gpkg", driver="GPKG")
            print(f"  Viety: {DATA_POLKU / 'kohteet.gpkg'}")
        except Exception as e:
            print(f"  ⚠ Vienti epäonnistui: {e}")

    return kohde


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

    # Sheet luodaan vain kerran per projekti
    if _lue_projekticonfig().get("sheets_id"):
        print("  Viranomaiskommenttien Sheet on jo luotu (sheets_id config.json:issa)")
    else:
        luo_projekti_sheet(PROJEKTI)

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
    print("  3 = Päivitä luokitukset GeoPackageen  (kaavoittaja + viranomainen)")
    tila = input("Valinta (1/2/3): ").strip()
    if tila not in ("1", "2", "3"):
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

    # --- Selaimessa näytettävät sarakkeet ---

    kysy_naytettavat_sarakkeet(gdf_3067)

    # ── TILA 3: LUOKITUSTEN PÄIVITYS ──────────────────────────────
    # Palaa tästä — kuvien käsittelyllä ei ole osaa tässä tilassa.

    if tila == "3":
        paivitetty = tila3_paivita_luokitukset(gpkg_polku, layer_nimi)
        if paivitetty is None:
            print("\nEi muutoksia.")
            input("Paina Enter sulkeaksesi...")
            return

        if input("\nViedäänkö kohteet.geojson ja pushataanko? (k/e): ").strip().lower() == "k":
            geojson_tilastot = vie_geojson(paivitetty, layer_nimi)
            print("\n--- Git push (data + config) ---")
            git_push(
                f"Päivitä luokitukset: {PROJEKTI}",
                f"projektit/{PROJEKTI}/",
                *kopioi_docsiin(),
            )
            print()
            print("=" * 60)
            print("  Valmis!")
            print(f"  GeoPackage:          {paivitetty}")
            print(f"  Rakennuksia kuvilla: "
                  f"{geojson_tilastot['kuvilla']} / {geojson_tilastot['rakennuksia']}")
            print("=" * 60)
        else:
            print()
            print("=" * 60)
            print("  Valmis!")
            print(f"  GeoPackage:          {paivitetty}")
            print("  GeoJSONia ei viety — kartta näyttää edellisen ajon datan.")
            print("=" * 60)

        input("\nPaina Enter sulkeaksesi...")
        return

    # ── TILA 1: PIPELINE ──────────────────────────────────────────

    if tila == "1":

        kuvakansio_str = input("\nKuvakansio (polku):\n> ").strip().strip('"')
        kuvakansio = Path(kuvakansio_str)
        if not kuvakansio.is_dir():
            print(f"VIRHE: Kansiota ei löydy: {kuvakansio}")
            input("Paina Enter sulkeaksesi...")
            return

        # --- Liitostapa ---
        # GeoPackagen kuva1..3 on kenttäsovelluksen oma kirjaus ja siksi
        # tarkempi kuin EXIF-GPS, jota GPX-geotägäyksen kellodrifti siirtää.
        print("\nMiten kuvat liitetään kohteisiin?")
        print("  1 = GeoPackagen kuvaviittaukset  (kuva1..3-sarakkeet)  [oletus]")
        print("  2 = GPS-etäisyys                 (EXIF + GPX-geotägäys)")
        liitostapa = input("Valinta (1/2) [1]: ").strip() or "1"
        if liitostapa not in ("1", "2"):
            print("Virheellinen valinta.")
            input("Paina Enter sulkeaksesi...")
            return

        if liitostapa == "1":
            puuttuvat_sarakkeet = [s for s in KUVA_SARAKKEET if s not in gdf_3067.columns]
            if len(puuttuvat_sarakkeet) == len(KUVA_SARAKKEET):
                print(f"VIRHE: GeoPackagesta puuttuvat sarakkeet {', '.join(KUVA_SARAKKEET)}"
                      " — käytä GPS-liitosta (valinta 2).")
                input("Paina Enter sulkeaksesi...")
                return
            tilastot = liita_kuvat_gpkg(kuvakansio, gdf_3067)
            kuvia_lisatty = tilastot["ok"]
            if kuvia_lisatty > 0 or tilastot["siirretty"] or tilastot["poistettu"]:
                print("\n--- Vaihe 3: Git push (kuvat) ---")
                git_push(
                    f"Liitä kuvat GeoPackagen viittauksista: {PROJEKTI}",
                    f"projektit/{PROJEKTI}/kuvat/",
                    f"projektit/{PROJEKTI}/data/{KASITELLYT_TIEDOSTO}",
                )
            else:
                print("\nVaihe 3 ohitettu — kuvat olivat jo paikallaan.")

            geojson_tilastot = vie_geojson(gpkg_polku, layer_nimi)
            print("\n--- Git push (data + config) ---")
            git_push(
                f"Päivitä kohteet.geojson ja config: {PROJEKTI}",
                f"projektit/{PROJEKTI}/",
                *kopioi_docsiin(),
            )
            print()
            print("=" * 60)
            print("  Valmis!")
            print(f"  Kuvia kopioitu:      {tilastot['ok']}")
            if tilastot["siirretty"]:
                print(f"  Paikkaa siirretty:   {tilastot['siirretty']}")
            if tilastot["poistettu"]:
                print(f"  Poistettu:           {tilastot['poistettu']}  (paikat täyttyivät)")
            if tilastot["ohitettu"]:
                print(f"  Ei löytynyt:         {tilastot['ohitettu']}  (viittaus ilman tiedostoa)")
            print(f"  Rakennuksia kuvilla: "
                  f"{geojson_tilastot['kuvilla']} / {geojson_tilastot['rakennuksia']}")
            print("=" * 60)
            input("\nPaina Enter sulkeaksesi...")
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
    # Tila 3 on käsitelty jo yllä, joten tähän päätyy vain tila 2.

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

    # Polku on projektikansio, ei pelkkä data/ — myös config.json pitää päätyä
    # GitHubiin, koska kartta lukee sieltä tasot, naytettavat_sarakkeet ja
    # apps_script_url.
    print("\n--- Git push (data + config) ---")
    git_push(
        f"Päivitä kohteet.geojson ja config: {PROJEKTI}",
        f"projektit/{PROJEKTI}/",
        *kopioi_docsiin(),
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
