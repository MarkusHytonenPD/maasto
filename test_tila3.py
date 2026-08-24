"""
Regressiotesti tilalle 3 — luokitusten päivitys GeoPackageen.

Kattaa:
  • kaavoittajan luokitus-GeoJSONin luku (karttasovelluksen lataama tiedosto)
  • viranomaissarakkeiden lisäys ja arvojen päivitys SQLitellä
  • KRIITTINEN: QGIS-tyylit (layer_styles) ja muut tasot säilyvät päivityksessä
  • GeoPackagen RTree-triggerien ST_*-funktiot (ilman niitä UPDATE kaatuu)
  • tunnuksen tyyppivariaatiot (63 / "63" / 63.0)
  • tallennus päälle ja uudella nimellä, GeoJSONin ohitus, tyhjä syöte

Ei verkkoa: viranomaisdata tyngätään. Live-testi Sheetsiä vasten on
erikseen test_sheets_live.py:ssä.

Ajo:
    python3 test_tila3.py

Palauttaa 0 jos kaikki väittämät menevät läpi, muuten 1.
"""
import builtins
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import geopandas as gpd
import pandas as pd

import pipeline as P

LAHDE_GEOJSON = REPO / "projektit" / "heinlansi_rak_kulttuuri" / "data" / "kohteet.geojson"

BASE = Path(tempfile.mkdtemp(prefix="tila3-testi-"))
tulokset = []


def ok(nimi, ehto, lisa=""):
    tulokset.append(bool(ehto))
    merkki = "OK  " if ehto else "FAIL"
    print(f"  {merkki} {nimi}" + (f" — {lisa}" if lisa else ""))


def _alusta_projekti(nimi="ZZ_testi"):
    P.PROJEKTI = nimi
    P.PROJEKTI_POLKU = BASE / nimi
    P.DATA_POLKU = P.PROJEKTI_POLKU / "data"
    P.KUVA_POLKU = P.PROJEKTI_POLKU / "kuvat"
    P.PROJEKTI_POLKU.mkdir(parents=True, exist_ok=True)
    P._kirjoita_projekticonfig({"nimi": nimi, "tasot": []})


def _luo_gpkg(gdf, nimi):
    """
    GeoPackage jossa on päälayer, TOINEN TASO ja QGIS-tyylitaulu.

    Viranomaissarakkeet pudotetaan, jotta lähtötilanne vastaa QGIS:stä
    tullutta inventointi-GeoPackagea: pipelinen on lisättävä ne itse
    ALTER TABLE:lla. Fikstuurin lähde-GeoJSON sisältää ne nykyään
    valmiina (tyhjinä), koska GeoJSON-vienti kirjoittaa pakolliset
    sarakkeet aina.
    """
    polku = BASE / nimi
    pudota = ["kuva1", "kuva2", "kuva3"] + P.VIRANOMAIS_SARAKKEET
    gdf.drop(columns=[c for c in pudota if c in gdf.columns]) \
       .to_file(polku, layer="ku", driver="GPKG")
    gdf.head(3).to_file(polku, layer="toinen_taso", driver="GPKG", mode="a")

    yhteys = sqlite3.connect(str(polku))
    yhteys.execute("""CREATE TABLE layer_styles (id INTEGER PRIMARY KEY,
                      f_table_name TEXT, styleName TEXT, styleQML TEXT)""")
    yhteys.execute("INSERT INTO layer_styles (f_table_name, styleName, styleQML) "
                   "VALUES (?, ?, ?)", ("ku", "Luokitustyyli", "<qgis>TÄRKEÄ TYYLI</qgis>"))
    yhteys.commit()
    yhteys.close()
    return polku


def _taulut(polku):
    yhteys = sqlite3.connect(str(polku))
    nimet = sorted(r[0] for r in yhteys.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    yhteys.close()
    return nimet


def _syotteet(*arvot):
    """Korvaa input() annetuilla vastauksilla järjestyksessä."""
    jono = iter(arvot)
    builtins.input = lambda *a, **k: next(jono)


def main():
    if not LAHDE_GEOJSON.is_file():
        print(f"OHITETTU: fikstuuria ei löydy: {LAHDE_GEOJSON}")
        return 0

    oikea_input = builtins.input
    gdf = gpd.read_file(LAHDE_GEOJSON).to_crs("EPSG:3067")
    lahde = json.loads(LAHDE_GEOJSON.read_text(encoding="utf-8"))
    tunnukset = [str(f["properties"]["tunnus"]) for f in lahde["features"]]

    print(f"Fikstuuri: {len(tunnukset)} kohdetta, väliaikaishakemisto {BASE}")
    _alusta_projekti()

    # ── 1. Kaavoittajan GeoJSONin luku ────────────────────────────
    print("\n1. Kaavoittajan luokitus-GeoJSONin luku")

    muutokset = {}
    data = json.loads(json.dumps(lahde))
    for i, piirre in enumerate(data["features"][:5]):
        arvo = ["suojelukohde", "paikallinen", "", "suojelukohde", "paikallinen"][i]
        piirre["properties"]["potentiaali"] = arvo
        muutokset[str(piirre["properties"]["tunnus"])] = arvo

    # Tunnus jota ei ole GeoPackagessa — pitää raportoida, ei kaatua
    tuntematon = json.loads(json.dumps(data["features"][0]))
    tuntematon["properties"]["tunnus"] = "EI_OLE_9999"
    tuntematon["properties"]["potentiaali"] = "suojelukohde"
    data["features"].append(tuntematon)

    kaava_polku = BASE / "kaavoittajan_suositus_ZZ_testi_2026-08-23.geojson"
    kaava_polku.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    kaava = P.lue_kaavoittajan_geojson(kaava_polku)
    ok("kaikki kohteet luettu", len(kaava) == len(tunnukset) + 1, len(kaava))
    ok("muutetut arvot oikein", all(kaava[t] == v for t, v in muutokset.items()))
    ok("puuttuva tiedosto ei kaada",
       P.lue_kaavoittajan_geojson(BASE / "ei-ole.geojson") == {})

    # ── 2. Tunnuksen normalisointi ────────────────────────────────
    print("\n2. Tunnuksen tyyppivariaatiot (GeoPackagessa teksti/int/float)")
    for syote, odotus in [(63, "63"), ("63", "63"), (63.0, "63"), (" 63 ", "63"),
                          (None, ""), ("102496631X", "102496631X"), (float("nan"), "")]:
        ok(f"_normalisoi_tunnus({syote!r}) → {odotus!r}",
           P._normalisoi_tunnus(syote) == odotus, P._normalisoi_tunnus(syote))

    # ── 3. Päivitys: tyylit ja muut tasot säilyvät ────────────────
    print("\n3. paivita_geopackage — tyylit, muut tasot, RTree-triggerit")

    viranomais = {
        # Sama kohde, kaksi eri tahoa: kummankin lausunto omiin sarakkeisiinsa
        tunnukset[0]: {"luokitus_lvv": "suojelukohde",
                       "kommentti_lvv": 'Kommentti "lainausmerkeillä" ja skandit äöå',
                       "nimi_lvv": "Testi Viranomainen",
                       "luokitus_museo": "paikallinen",
                       "kommentti_museo": "Museon eri kanta",
                       "nimi_museo": "Museon Tarkastaja"},
        tunnukset[7]: {"luokitus_liitto": "paikallinen", "kommentti_liitto": "",
                       "nimi_liitto": "Liiton Tarkastaja"},
        "EI_OLE_8888": {"luokitus_lvv": "suojelukohde"},
    }

    gpkg = _luo_gpkg(gdf, "paivitys.gpkg")
    taulut_ennen = _taulut(gpkg)
    tilastot = P.paivita_geopackage(gpkg, "ku", kaava, viranomais)

    ok("kaavoittajan päivitykset", tilastot["kaava_ok"] == len(tunnukset),
       tilastot["kaava_ok"])
    ok("viranomaispäivitykset", tilastot["vir_ok"] == 2, tilastot["vir_ok"])
    ok("puuttuvat tunnukset raportoitu",
       tilastot["puuttuvat"] == ["EI_OLE_8888", "EI_OLE_9999"], tilastot["puuttuvat"])
    ok("viranomaissarakkeet lisättiin",
       tilastot["lisatyt_sarakkeet"] == P.VIRANOMAIS_SARAKKEET,
       tilastot["lisatyt_sarakkeet"])

    ok("KRIITTINEN: layer_styles säilyi", "layer_styles" in _taulut(gpkg))
    ok("KRIITTINEN: toinen_taso säilyi", "toinen_taso" in _taulut(gpkg))
    ok("yhtään taulua ei kadonnut",
       set(taulut_ennen) <= set(_taulut(gpkg)),
       sorted(set(taulut_ennen) - set(_taulut(gpkg))))

    yhteys = sqlite3.connect(str(gpkg))
    tyyli = yhteys.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name='ku'").fetchone()
    ok("QGIS-tyylin sisältö ennallaan", tyyli and "TÄRKEÄ TYYLI" in tyyli[0])
    ok("toinen_taso ennallaan (3 riviä)",
       yhteys.execute("SELECT count(*) FROM toinen_taso").fetchone()[0] == 3)
    yhteys.close()

    paivitetty = gpd.read_file(gpkg, layer="ku")
    rivi = paivitetty[paivitetty["tunnus"].astype(str) == tunnukset[0]].iloc[0]
    ok("kaavoittajan arvo tallentui", rivi["potentiaali"] == muutokset[tunnukset[0]],
       rivi["potentiaali"])
    ok("viranomaisarvot tallentuivat",
       rivi["luokitus_lvv"] == "suojelukohde"
       and rivi["nimi_lvv"] == "Testi Viranomainen")
    ok("saman kohteen toisen tahon lausunto omissa sarakkeissaan",
       rivi["luokitus_museo"] == "paikallinen"
       and rivi["nimi_museo"] == "Museon Tarkastaja"
       and rivi["luokitus_liitto"] in ("", None),
       f'museo={rivi["luokitus_museo"]!r} liitto={rivi["luokitus_liitto"]!r}')
    ok("lainausmerkit ja skandit säilyivät",
       rivi["kommentti_lvv"] == 'Kommentti "lainausmerkeillä" ja skandit äöå',
       rivi["kommentti_lvv"])
    ok("geometria ja rivimäärä ennallaan",
       paivitetty.geometry.notna().all() and len(paivitetty) == len(tunnukset))

    lausunnoton = paivitetty[paivitetty["tunnus"].astype(str) == tunnukset[2]] \
                  ["luokitus_lvv"].iloc[0]
    ok("kohde ilman lausuntoa jäi tyhjäksi",
       lausunnoton is None or pd.isna(lausunnoton) or str(lausunnoton).strip() == "",
       repr(lausunnoton))

    print("\n4. Väärä layer-nimi")
    try:
        P.paivita_geopackage(gpkg, "ei_ole_layer", {}, {})
        ok("virhe nostettiin", False)
    except ValueError as e:
        ok("virhe kertoo löytyneet layerit", "ku" in str(e), str(e)[:80])

    # ── 5. Tila 3 -kulku: tallennus uudella nimellä ───────────────
    print("\n5. tila3_paivita_luokitukset — tallennus uudella nimellä")
    P.hae_viranomaisdata = lambda: viranomais   # ei verkkoa

    alkuperainen = _luo_gpkg(gdf, "uusinimi.gpkg")
    koko_ennen = alkuperainen.stat().st_size
    _syotteet(str(kaava_polku), "2", "", "k")   # geojson, uusi nimi, oletusnimi, vie gpkg
    kohde = P.tila3_paivita_luokitukset(alkuperainen, "ku")

    ok("palautti uuden tiedoston",
       kohde is not None and kohde.name == "uusinimi_paivitetty.gpkg",
       kohde.name if kohde else None)
    ok("alkuperäinen ei muuttunut", alkuperainen.stat().st_size == koko_ennen)
    ok("alkuperäisessä ei viranomaissarakkeita",
       "luokitus_lvv" not in gpd.read_file(alkuperainen, layer="ku").columns)
    kopio = gpd.read_file(kohde, layer="ku")
    ok("kopiossa on viranomaissarakkeet",
       all(s in kopio.columns for s in P.VIRANOMAIS_SARAKKEET))
    ok("kopiossa oikeat arvot",
       kopio[kopio["tunnus"].astype(str) == tunnukset[0]]["nimi_lvv"].iloc[0]
       == "Testi Viranomainen")
    yhteys = sqlite3.connect(str(kohde))
    ok("tyyli säilyi kopiossa",
       "TÄRKEÄ TYYLI" in yhteys.execute("SELECT styleQML FROM layer_styles").fetchone()[0])
    yhteys.close()
    ok("kohteet.gpkg viety projektikansioon", (P.DATA_POLKU / "kohteet.gpkg").is_file())

    # ── 6. Tallennus päälle ───────────────────────────────────────
    print("\n6. tila3_paivita_luokitukset — tallennus päälle")
    paalle = _luo_gpkg(gdf, "paalle.gpkg")
    _syotteet(str(kaava_polku), "1", "e")       # geojson, päälle, ei kohteet.gpkg:tä
    kohde = P.tila3_paivita_luokitukset(paalle, "ku")

    ok("kohde on alkuperäinen tiedosto", kohde == paalle, kohde)
    u = gpd.read_file(paalle, layer="ku")
    ok("arvot päivittyivät alkuperäiseen",
       u[u["tunnus"].astype(str) == tunnukset[0]]["nimi_lvv"].iloc[0] == "Testi Viranomainen")
    yhteys = sqlite3.connect(str(paalle))
    ok("tyyli säilyi päällekirjoituksessa",
       "TÄRKEÄ TYYLI" in yhteys.execute("SELECT styleQML FROM layer_styles").fetchone()[0])
    yhteys.close()

    # ── 7. GeoJSON ohitetaan ──────────────────────────────────────
    print("\n7. Pelkkä viranomaisdata (GeoJSON ohitetaan Enterillä)")
    vain_vir = _luo_gpkg(gdf, "vain_vir.gpkg")
    _syotteet("", "1", "e")
    P.tila3_paivita_luokitukset(vain_vir, "ku")
    u = gpd.read_file(vain_vir, layer="ku")
    ok("viranomaisdata päivittyi",
       u[u["tunnus"].astype(str) == tunnukset[0]]["nimi_lvv"].iloc[0] == "Testi Viranomainen")
    ok("kaavoittajan arvot ennallaan",
       u[u["tunnus"].astype(str) == tunnukset[0]]["potentiaali"].iloc[0]
       == lahde["features"][0]["properties"]["potentiaali"],
       u[u["tunnus"].astype(str) == tunnukset[0]]["potentiaali"].iloc[0])

    # ── 8. Ei dataa kummastakaan ──────────────────────────────────
    print("\n8. Ei dataa kummastakaan lähteestä")
    P.hae_viranomaisdata = lambda: {}
    tyhja = _luo_gpkg(gdf, "tyhja.gpkg")
    _syotteet("")
    ok("palauttaa None", P.tila3_paivita_luokitukset(tyhja, "ku") is None)
    ok("GeoPackageen ei koskettu",
       "luokitus_lvv" not in gpd.read_file(tyhja, layer="ku").columns)

    builtins.input = oikea_input
    return 0 if all(tulokset) else 1


if __name__ == "__main__":
    koodi = main()
    print()
    print("=" * 60)
    if koodi == 0:
        print("  KAIKKI OK" + f"  ({len(tulokset)} väittämää)")
        import shutil
        shutil.rmtree(BASE, ignore_errors=True)
    else:
        print(f"  {tulokset.count(False)}/{len(tulokset)} VÄITTÄMÄÄ EPÄONNISTUI")
        print(f"  Väliaikaishakemisto jätettiin tutkittavaksi: {BASE}")
    print("=" * 60)
    raise SystemExit(koodi)
