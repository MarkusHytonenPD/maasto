"""
Selaintesti karttasovellukselle (docs/kartta.js, docs/kartta.css).

Ajaa oikean sivun oikeassa selaimessa (Playwright + Chromium) ja ohjaa
GitHub raw -pyynnöt paikallisiin fikstuureihin, joten testi ei kosketa
verkkoon eikä muokkaa docs/-kansion tiedostoja.

Kattaa:
  • pisteiden väritys molemmissa näkymissä (LUOKAT-taulukko)
  • tunnusotsikot kartalla (aina näkyvät, eivät nappaa klikkauksia)
  • popup: naytettavat_sarakkeet, kuvat, tyhjien kenttien ohitus
  • kaavoittajan luokituspainikkeet, localStorage, värin päivitys heti
  • "Lataa kaavoittajan suositukset" -tiedoston sisältö
  • viranomaisen lomake: esitäyttö, POST-runko, onnistuminen ja virheet
  • Sheetsin tuore data voittaa GeoJSONin arvot
  • nimen ja viraston muistaminen
  • XSS: attribuuttidatan HTML ei suoriudu
  • datan lähde: Pages-kopio ensin, raw.githubusercontent.com varalla

Ajo:
    python3 test_kartta.py

Vaatii:
    pip install playwright && playwright install chromium
"""
import base64
import functools
import http.server
import json
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

REPO   = Path(__file__).resolve().parent
DOCS   = REPO / "docs"
LAHDE  = REPO / "projektit" / "heinlansi_rak_kulttuuri" / "data" / "kohteet.geojson"
KUVAT  = REPO / "projektit" / "heinlansi_rak_kulttuuri" / "kuvat"

RAW       = "https://raw.githubusercontent.com/MarkusHytonenPD/maasto/main/"
PROJEKTI  = "ZZ_selaintesti"
ENDPOINT  = "https://apps-script.test/exec"

# 1×1 px PNG karttalaattojen tilalle — testi ei kutsu MML:ää
LAATTA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP4//8/AAX+Av7czFnnAAAAAElFTkSuQmCC")

NAYTA = ["tunnus", "vuosi", "huom", "suojeluhalu"]

# Kommenttiin tarkoituksella HTML:ää ja lainausmerkkejä
XSS = 'Arvokas pihapiiri, "erittäin" hyvä <script>window.HAKKEROITU = 1</script>'

tulokset = []


def ok(nimi, ehto, lisa=""):
    tulokset.append(bool(ehto))
    merkki = "OK  " if ehto else "FAIL"
    print(f"  {merkki} {nimi}" + (f" — {lisa}" if lisa else ""))


def luo_fikstuuri(kansio: Path):
    """Rakentaa projektin config.json:in ja kohteet.geojsonin oikeasta datasta."""
    data = json.loads(LAHDE.read_text(encoding="utf-8"))
    kohde = kansio / "projektit" / PROJEKTI
    (kohde / "data").mkdir(parents=True, exist_ok=True)

    for i, piirre in enumerate(data["features"]):
        vanhat = piirre["properties"]
        uudet = {k: vanhat.get(k, "") for k in NAYTA}
        uudet["potentiaali"] = vanhat.get("potentiaali") or ""
        for sarake in ("luokitus_vir", "kommentti_vir", "nimi_vir", "virasto_vir"):
            uudet[sarake] = ""
        for sarake in ("kuva1", "kuva2", "kuva3"):
            uudet[sarake] = vanhat.get(sarake) or ""
        if i == 0:                       # kohde jolla on viranomaislausunto
            uudet["luokitus_vir"]  = "suojelukohde"
            uudet["kommentti_vir"] = XSS
            uudet["nimi_vir"]      = "Testi Viranomainen"
            uudet["virasto_vir"]   = "Museovirasto"
        if i == 1:
            uudet["luokitus_vir"] = "paikallinen"
            uudet["nimi_vir"]     = "Toinen Tarkastaja"
        piirre["properties"] = uudet

    (kohde / "data" / "kohteet.geojson").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (kohde / "config.json").write_text(json.dumps({
        "nimi": "Selaintesti", "tasot": [],
        "naytettavat_sarakkeet": NAYTA,
        "sheets_id": "PAIKANVARAAJA", "sheets_valilehti": "Lausunnot",
        "apps_script_url": "",
    }, ensure_ascii=False, indent=4), encoding="utf-8")
    return data


class _Kasittelija(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler ilman pyyntölokia testin tulosteessa."""
    def log_message(self, *args):
        pass


def _palvele(kansio: Path):
    """Käynnistää paikallisen http-palvelimen. Palauttaa (palvelin, portti)."""
    class Palvelin(http.server.ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    palvelin = Palvelin(("127.0.0.1", 0),
                        functools.partial(_Kasittelija, directory=str(kansio)))
    threading.Thread(target=palvelin.serve_forever, daemon=True).start()
    return palvelin, palvelin.server_address[1]


def testaa_datan_lahde(base: Path, data: dict, virheet: list) -> list:
    """
    Varmistaa että kartta lukee datan Pages-kopiosta kun se on olemassa ja
    raw:sta kun ei ole. Pages tyhjentää välimuistinsa deployssa, joten
    pipeline-ajon tulokset näkyvät heti; raw pitää tiedostoa max-age=300
    eikä revalidoi pyynnöstä.

    Sivu tarjoillaan paikallisesta http-palvelimesta, koska file://-sivulla
    suhteellista fetchiä ei voi tehdä.
    """
    from playwright.sync_api import sync_playwright

    lahde   = base / "projektit" / PROJEKTI
    pages   = base / "docs"
    projekti_docs = pages / PROJEKTI
    (projekti_docs / "data").mkdir(parents=True, exist_ok=True)
    for nimi in ("kartta.js", "kartta.css", "config.js", "index.html"):
        shutil.copy2(DOCS / nimi, pages / nimi)

    # Projektikohtainen sivu (window.PROJEKTI) — pipelinen luoman kaltainen
    (projekti_docs / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="fi"><head><meta charset="UTF-8" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="../kartta.css" /></head><body>
<div id="map"></div>
<div id="lightbox"><span id="lightbox-sulje">x</span><img id="lightbox-kuva" src="" alt="" /></div>
<script>window.PROJEKTI = "{PROJEKTI}";</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/proj4@2.11.0/dist/proj4.js"></script>
<script src="https://unpkg.com/proj4leaflet@1.0.2/src/proj4leaflet.js"></script>
<script src="../config.js"></script><script src="../kartta.js"></script>
</body></html>""", encoding="utf-8")

    # Lähteet erotetaan toisistaan nimellä ja kohdemäärällä
    pohja = json.loads((lahde / "config.json").read_text(encoding="utf-8"))
    (projekti_docs / "config.json").write_text(
        json.dumps(dict(pohja, nimi="PAGES"), ensure_ascii=False), encoding="utf-8")
    shutil.copy2(lahde / "data" / "kohteet.geojson",
                 projekti_docs / "data" / "kohteet.geojson")

    raw_cfg     = json.dumps(dict(pohja, nimi="RAW"), ensure_ascii=False)
    raw_geojson = json.dumps({"type": "FeatureCollection",
                              "features": data["features"][:1]}, ensure_ascii=False)

    def raw(route, pyynto):
        polku = pyynto.url[len(RAW):].split("?")[0]
        if polku.endswith("config.json"):
            route.fulfill(status=200, content_type="application/json", body=raw_cfg)
        elif polku.endswith("kohteet.geojson"):
            route.fulfill(status=200, content_type="application/json", body=raw_geojson)
        else:
            route.fulfill(status=404, body="ei löydy")

    def lataa(konteksti, url):
        sivu = konteksti.new_page()
        pyynnot = []
        sivu.on("request", lambda p: pyynnot.append(p.url))
        sivu.on("console", lambda m: virheet.append(m.text)
                if m.type == "error" and "Failed to load resource" not in m.text else None)
        sivu.on("pageerror", lambda e: virheet.append(f"pageerror: {e}"))
        sivu.route(RAW + "**", raw)
        sivu.route("**maanmittauslaitos.fi/**",
                   lambda r, q: r.fulfill(status=200, body=LAATTA, content_type="image/png"))
        sivu.goto(url, wait_until="load")
        sivu.wait_for_timeout(2500)
        tila = {
            "nimi":    sivu.evaluate("projektiConfig.nimi"),
            "kohteet": sivu.evaluate("geojsonData ? geojsonData.features.length : 0"),
            "pyynnot": pyynnot,
        }
        sivu.close()
        return tila

    palvelin, portti = _palvele(pages)
    juuri = f"http://127.0.0.1:{portti}"
    odotettu = f"{juuri}/{PROJEKTI}/config.json?v="
    tulokset = []
    try:
        with sync_playwright() as pw:
            selain    = pw.chromium.launch()
            konteksti = selain.new_context()

            juuresta = lataa(konteksti, f"{juuri}/index.html?projekti={PROJEKTI}")
            tulokset.append(("juurisivu lukee Pages-kopion",
                             juuresta["nimi"] == "PAGES"
                             and juuresta["kohteet"] == len(data["features"]),
                             f'{juuresta["nimi"]}, {juuresta["kohteet"]} kohdetta'))
            tulokset.append(("haussa on välimuistin ohittava aikaleima",
                             any(u.startswith(odotettu) for u in juuresta["pyynnot"]),
                             odotettu))

            projektisivu = lataa(konteksti, f"{juuri}/{PROJEKTI}/index.html")
            tulokset.append(("projektisivu lukee Pages-kopion samasta kansiosta",
                             projektisivu["nimi"] == "PAGES"
                             and any(u.startswith(odotettu) for u in projektisivu["pyynnot"]),
                             projektisivu["nimi"]))

            # Ilman Pages-kopiota kartan on toimittava raw:n varassa
            (projekti_docs / "config.json").unlink()
            (projekti_docs / "data" / "kohteet.geojson").unlink()
            varalta = lataa(konteksti, f"{juuri}/index.html?projekti={PROJEKTI}")
            tulokset.append(("ilman Pages-kopiota data tulee raw:sta",
                             varalta["nimi"] == "RAW" and varalta["kohteet"] == 1,
                             f'{varalta["nimi"]}, {varalta["kohteet"]} kohdetta'))
            selain.close()
    finally:
        palvelin.shutdown()
        palvelin.server_close()
    return tulokset


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("OHITETTU: Playwright puuttuu.")
        print("  Asenna: pip install playwright && playwright install chromium")
        return 0

    if not LAHDE.is_file():
        print(f"OHITETTU: fikstuuria ei löydy: {LAHDE}")
        return 0

    base = Path(tempfile.mkdtemp(prefix="kartta-testi-"))
    data = luo_fikstuuri(base)
    kuva = next(iter(sorted(KUVAT.glob("*.jpg"))), None)

    piirteet = data["features"]
    T0       = str(piirteet[0]["properties"]["tunnus"])   # viranomaislausunto + XSS
    T_TYHJA  = str(piirteet[3]["properties"]["tunnus"])   # ei lausuntoa
    T_HUOM   = next((str(f["properties"]["tunnus"]) for f in piirteet
                     if f["properties"].get("huom")), None)

    # Sheetsissä T0:lla on TUOREEMPI, eri lausunto kuin GeoJSONissa
    SHEETS_RIVIT = [{"tunnus": T0, "luokitus_vir": "paikallinen",
                     "kommentti_vir": "Sheetsistä haettu tuore kommentti",
                     "nimi_vir": "Sheets Tarkastaja", "virasto_vir": "ELY-keskus"}]

    virheet, postit = [], []

    def aja(apps_url, post_vastaus, testit):
        with sync_playwright() as pw:
            selain = pw.chromium.launch()
            sivu = selain.new_page(viewport={"width": 1000, "height": 950})
            # Tahallisen HTTP-virheen verkkoloki ei ole sovelluksen virhe
            sivu.on("console", lambda m: virheet.append(m.text)
                    if m.type == "error" and "Failed to load resource" not in m.text else None)
            sivu.on("pageerror", lambda e: virheet.append(f"pageerror: {e}"))

            def raw(route, pyynto):
                # Kartta lisää välimuistin ohittavan ?v=… -parametrin
                polku = pyynto.url[len(RAW):].split("?")[0]
                if polku.endswith(".jpg") and kuva:
                    route.fulfill(status=200, body=kuva.read_bytes(),
                                  content_type="image/jpeg")
                    return
                if polku == f"projektit/{PROJEKTI}/config.json":
                    cfg = json.loads((base / polku).read_text(encoding="utf-8"))
                    cfg["apps_script_url"] = apps_url
                    route.fulfill(status=200, body=json.dumps(cfg),
                                  content_type="application/json")
                    return
                tiedosto = (base / polku) if polku.startswith(f"projektit/{PROJEKTI}/") \
                           else (REPO / polku)
                if tiedosto.is_file():
                    route.fulfill(status=200, body=tiedosto.read_bytes())
                else:
                    route.fulfill(status=404, body="ei löydy")

            def endpoint(route, pyynto):
                if pyynto.method == "POST":
                    postit.append({"headers": pyynto.headers,
                                   "body": json.loads(pyynto.post_data)})
                    route.fulfill(**post_vastaus)
                else:
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"status": "ok", "rivit": SHEETS_RIVIT}))

            sivu.route(RAW + "**", raw)
            sivu.route("https://apps-script.test/**", endpoint)
            sivu.route("**maanmittauslaitos.fi/**",
                       lambda r, q: r.fulfill(status=200, body=LAATTA,
                                              content_type="image/png"))

            sivu.goto(f"file://{DOCS}/index.html?projekti={PROJEKTI}")
            sivu.wait_for_timeout(2500)
            testit(sivu)
            selain.close()

    def varit(sivu):
        return sivu.evaluate("""() => {
          const laske = {};
          document.querySelectorAll('path.leaflet-interactive').forEach(p => {
            const v = p.getAttribute('fill'); laske[v] = (laske[v] || 0) + 1; });
          return laske; }""")

    def avaa(sivu, tunnus):
        """Sulkee edellisen popupin ensin — Leaflet jättää DOM:n hetkeksi."""
        sivu.evaluate("map.closePopup()")
        try:
            sivu.wait_for_selector(".pu", state="detached", timeout=3000)
        except Exception:
            pass
        sivu.evaluate(f"markkerit[{json.dumps(str(tunnus))}].openPopup()")
        sivu.wait_for_selector(".pu", timeout=5000)

    # ══ 1. Kaavoittajan näkymä ═══════════════════════════════════
    print("\n1. Kaavoittajan näkymä, luokitus ja lataus")

    def testit1(sivu):
        maara = sivu.eval_on_selector_all("path.leaflet-interactive", "e => e.length")
        ok("kaikki pisteet piirtyivät", maara == len(piirteet), f"{maara} kpl")

        otsikot_kartalla = sivu.eval_on_selector_all(
            ".leaflet-tooltip.tunnus-otsikko", "e => e.map(x => x.textContent)")
        ok("tunnus näkyy kartalla joka pisteellä",
           sorted(otsikot_kartalla) == sorted(str(f["properties"]["tunnus"]) for f in piirteet),
           f"{len(otsikot_kartalla)} otsikkoa")
        tyyli = sivu.eval_on_selector(
            ".leaflet-tooltip.tunnus-otsikko",
            "e => { const s = getComputedStyle(e);"
            "  return {tausta: s.backgroundColor, hiiri: s.pointerEvents}; }")
        ok("otsikko on läpinäkyvä eikä nappaa klikkauksia",
           tyyli["tausta"] == "rgba(0, 0, 0, 0)" and tyyli["hiiri"] == "none", tyyli)

        v = varit(sivu)
        ok("värit LUOKAT-taulukon mukaan",
           v.get("#999999", 0) + v.get("#1f78b4", 0) + v.get("#e31a1c", 0) == len(piirteet)
           and v.get("#1f78b4") == 14 and v.get("#e31a1c") == 8, v)

        ok("näkymävalitsimen tekstit",
           sivu.text_content("#nakyma-kaavoittaja") == "Kaavoittajan suositus"
           and sivu.text_content("#nakyma-viranomainen") == "Viranomaisen luokitus")
        ok("latausnappi näkyy",
           "Lataa kaavoittajan suositukset" in sivu.text_content("#lataa-suositukset"))

        avaa(sivu, T0)
        otsikot = sivu.eval_on_selector_all(".pu > .pu-attr td:first-child",
                                            "e => e.map(x => x.textContent)")
        ok("popup näyttää vain valitut sarakkeet",
           otsikot == ["tunnus", "vuosi", "suojeluhalu"], otsikot)
        ok("tyhjä sarake (huom) jätetään pois", "huom" not in otsikot)
        ok("viranomaissarakkeet eivät ole ylätaulussa",
           not any(o.startswith("Viranomaisen") for o in otsikot))
        ok("kuvat popupissa", sivu.eval_on_selector_all(".pu-kuvat img", "e => e.length") >= 1)

        # Näkymävalitsin ei saa peittää popupia. Z-indeksillä tätä ei voi
        # ratkaista (map pane on oma pinoamiskonteksti), vaan autoPanPadding
        # panoroi kartan — testataan siis lopputulos, ei tyyliarvoja.
        sivu.evaluate("map.closePopup()")
        sivu.wait_for_timeout(300)
        # Kohde siirretään täsmälleen näkymävalitsimen viereen, jottei testi
        # riipu aineiston sijainneista
        sivu.evaluate(f"""() => {{
            const m = markkerit[{json.dumps(T0)}];
            m.setLatLng(map.containerPointToLatLng([120, 200]));
            m.openPopup();
        }}""")
        sivu.wait_for_selector(".pu", timeout=5000)
        sivu.wait_for_timeout(1500)          # autoPanin panorointi
        peitto = sivu.evaluate("""() => {
            const p = document.querySelector('.leaflet-popup').getBoundingClientRect();
            const c = document.querySelector('.nakyma-control').getBoundingClientRect();
            const leveys  = Math.min(p.right, c.right) - Math.max(p.left, c.left);
            const korkeus = Math.min(p.bottom, c.bottom) - Math.max(p.top, c.top);
            return {leikkaus: Math.max(0, leveys) * Math.max(0, korkeus),
                    popupVasen: p.left | 0, kontrolliOikea: c.right | 0};
        }""")
        ok("näkymävalitsin ei peitä popupia", peitto["leikkaus"] == 0, peitto)

        napit = sivu.eval_on_selector_all(".pu-kaava .pu-napit button",
                                          "e => e.map(x => x.textContent)")
        ok("kolme luokituspainiketta",
           napit == ["Ei merkintää", "Suositus säilyttämisestä", "Suojelukohde"], napit)
        ok("aktiivinen vastaa nykyistä arvoa",
           sivu.eval_on_selector_all(".pu-kaava .pu-napit button.aktiivinen",
                                     "e => e.map(x => x.textContent)")
           == ["Suositus säilyttämisestä"])

        vir = sivu.text_content(".pu-vir")
        ok("viranomaisen lausunto näkyy (vain luku)",
           "Museovirasto" in vir and "Suojelukohde" in vir)
        ok("XSS ei suoriutunut",
           sivu.evaluate("window.HAKKEROITU === undefined")
           and "<script>" in sivu.inner_text(".pu-vir"))

        if T_HUOM:
            avaa(sivu, T_HUOM)
            ok("täytetty huom-sarake näkyy",
               "huom" in sivu.eval_on_selector_all(".pu > .pu-attr td:first-child",
                                                   "e => e.map(x => x.textContent)"))
            ok("ilman lausuntoa näkyy huomautus",
               sivu.text_content(".pu-vir-tyhja") == "Ei viranomaislausuntoa")

        # Luokituksen muutos
        avaa(sivu, T0)
        ennen = sivu.evaluate(f"markkerit[{json.dumps(T0)}].options.fillColor")
        sivu.click(".pu-kaava .pu-napit button:nth-child(3)")     # Suojelukohde
        sivu.wait_for_timeout(300)
        ok("pisteen väri päivittyi heti",
           ennen == "#1f78b4"
           and sivu.evaluate(f"markkerit[{json.dumps(T0)}].options.fillColor") == "#e31a1c")
        ok("aktiivinen korostus siirtyi",
           sivu.eval_on_selector_all(".pu-kaava .pu-napit button.aktiivinen",
                                     "e => e.map(x => x.textContent)") == ["Suojelukohde"])
        ok("localStorage-avain ja arvo",
           json.loads(sivu.evaluate(
               f"localStorage.getItem('luokitukset_kentta_{PROJEKTI}')"))
           == {T0: "suojelukohde"})

        # Näkymän vaihto
        sivu.click("#nakyma-viranomainen")
        sivu.wait_for_timeout(600)
        v = varit(sivu)
        ok("viranomaisnäkymä värittyy luokitus_vir:n mukaan",
           v.get("#e31a1c") == 1 and v.get("#1f78b4") == 1, v)
        avaa(sivu, T0)
        ok("kaavoittajan osio on vain luku viranomaisnäkymässä",
           sivu.eval_on_selector_all(".pu-kaava .pu-napit button", "e => e.length") == 0
           and sivu.text_content(".pu-lukuarvo") == "Suojelukohde")

        sivu.click("#nakyma-kaavoittaja")
        sivu.wait_for_timeout(500)
        ok("muutos säilyi näkymän vaihdon yli",
           sivu.evaluate(f"markkerit[{json.dumps(T0)}].options.fillColor") == "#e31a1c")
        ok("tunnusotsikot piirtyivät uudelleen näkymän vaihdossa",
           sivu.eval_on_selector_all(".leaflet-tooltip.tunnus-otsikko", "e => e.length")
           == len(piirteet))

        # Lataus
        with sivu.expect_download(timeout=10000) as odota:
            sivu.click("#lataa-suositukset")
        lataus = odota.value
        polku = Path(tempfile.mkdtemp()) / "ladattu.geojson"
        lataus.save_as(polku)
        ladattu = json.loads(polku.read_text(encoding="utf-8"))

        ok("tiedostonimi",
           re.fullmatch(rf"kaavoittajan_suositus_{PROJEKTI}_\d{{4}}-\d\d-\d\d\.geojson",
                        lataus.suggested_filename), lataus.suggested_filename)
        muutettu = [f["properties"] for f in ladattu["features"]
                    if str(f["properties"]["tunnus"]) == T0][0]
        ok("muutettu arvo tiedostossa", muutettu["potentiaali"] == "suojelukohde")
        muut = [f["properties"]["potentiaali"] for f in ladattu["features"]
                if str(f["properties"]["tunnus"]) != T0]
        ok("muut kohteet ennallaan",
           muut.count("paikallinen") == 13 and muut.count("suojelukohde") == 8,
           f"paikallinen={muut.count('paikallinen')} suojelukohde={muut.count('suojelukohde')}")
        ok("kohdemäärä säilyi", len(ladattu["features"]) == len(piirteet))

    aja("", {"status": 200, "body": "{}"}, testit1)

    # ══ 2. Viranomaisen lomake, onnistuva tallennus ═══════════════
    print("\n2. Viranomaisen lomake ja onnistuva tallennus")

    def testit2(sivu):
        ok("Sheetsin rivit haettiin",
           sivu.evaluate("Object.keys(sheetsLausunnot).length") == 1)
        sivu.click("#nakyma-viranomainen")
        sivu.wait_for_timeout(600)
        ok("väri Sheetsin arvosta, ei GeoJSONista",
           sivu.evaluate(f"markkerit[{json.dumps(T0)}].options.fillColor") == "#1f78b4",
           sivu.evaluate(f"markkerit[{json.dumps(T0)}].options.fillColor"))

        avaa(sivu, T0)
        sivu.wait_for_selector(".pu-vir-lomake", timeout=5000)
        ok("lomake esitäytetty Sheetsin arvoilla",
           sivu.input_value(".pu-vir-lomake textarea")
           == "Sheetsistä haettu tuore kommentti")
        ok("aktiivinen luokitus Sheetsistä",
           sivu.eval_on_selector_all(".pu-vir-lomake .pu-napit button.aktiivinen",
                                     "e => e.map(x => x.textContent)")
           == ["Suositus säilyttämisestä"])

        sivu.fill(".pu-vir-lomake textarea", "Uusi kommentti selaimesta")
        sivu.fill(".pu-vir-lomake .pu-kentta:nth-of-type(2) input", "Markus Testaaja")
        sivu.fill(".pu-vir-lomake .pu-kentta:nth-of-type(3) input", "Maakuntamuseo")
        sivu.click(".pu-vir-lomake .pu-napit button:nth-child(3)")   # Suojelukohde
        sivu.click(".pu-lomake-footer button")
        sivu.wait_for_selector(".pu-lomake-viesti.onnistui", timeout=5000)

        ok("vahvistusviesti", "päivitetty" in sivu.text_content(".pu-lomake-viesti"),
           sivu.text_content(".pu-lomake-viesti"))
        ok("POST tehtiin", len(postit) == 1)
        ok("Content-Type text/plain (ei OPTIONS-preflightiä)",
           postit[-1]["headers"].get("content-type", "").startswith("text/plain"),
           postit[-1]["headers"].get("content-type"))
        ok("POST-runko oikea", postit[-1]["body"] == {
            "tunnus": T0, "luokitus_vir": "suojelukohde",
            "kommentti_vir": "Uusi kommentti selaimesta",
            "nimi_vir": "Markus Testaaja", "virasto_vir": "Maakuntamuseo"},
           postit[-1]["body"])
        ok("väri päivittyi tallennuksesta",
           sivu.evaluate(f"markkerit[{json.dumps(T0)}].options.fillColor") == "#e31a1c")
        ok("nimi ja virasto muistiin",
           json.loads(sivu.evaluate("localStorage.getItem('viranomainen_tiedot')"))
           == {"nimi": "Markus Testaaja", "virasto": "Maakuntamuseo"})

        avaa(sivu, T_TYHJA)
        sivu.wait_for_selector(".pu-vir-lomake", timeout=5000)
        ok("nimi ja virasto esitäytetty muistista",
           sivu.input_value(".pu-vir-lomake .pu-kentta:nth-of-type(2) input")
           == "Markus Testaaja"
           and sivu.input_value(".pu-vir-lomake .pu-kentta:nth-of-type(3) input")
           == "Maakuntamuseo")
        ok("kommentti tyhjä uudelle kohteelle",
           sivu.input_value(".pu-vir-lomake textarea") == "")

        sivu.evaluate("map.closePopup()")
        sivu.click("#nakyma-kaavoittaja")
        sivu.wait_for_timeout(500)
        avaa(sivu, T0)
        ok("kaavoittajan näkymässä ei Tallenna-nappia",
           sivu.eval_on_selector_all(".pu-vir-lomake", "e => e.length") == 0
           and sivu.eval_on_selector_all(".pu-lomake-footer", "e => e.length") == 0)
        ok("kaavoittajan näkymä näyttää juuri tallennetun lausunnon",
           "Markus Testaaja" in sivu.text_content(".pu-vir")
           and "Maakuntamuseo" in sivu.text_content(".pu-vir"))

    aja(ENDPOINT, {"status": 200, "content_type": "application/json",
                   "body": json.dumps({"status": "ok", "toiminto": "paivitetty",
                                       "tunnus": T0})}, testit2)

    # ══ 3. Virhepolut ════════════════════════════════════════════
    print("\n3. Endpoint palauttaa virheen")

    def testit3(sivu):
        sivu.click("#nakyma-viranomainen")
        sivu.wait_for_timeout(600)
        avaa(sivu, T0)
        sivu.wait_for_selector(".pu-vir-lomake", timeout=5000)
        sivu.click(".pu-lomake-footer button")
        sivu.wait_for_selector(".pu-lomake-viesti.virhe", timeout=5000)
        viesti = sivu.text_content(".pu-lomake-viesti")
        ok("virheilmoitus kertoo syyn ja ettei tallentunut",
           "Taulukko on varattu" in viesti and "EI tallennettu" in viesti, viesti)
        ok("nappi palautuu käytettäväksi",
           sivu.eval_on_selector(".pu-lomake-footer button", "e => e.disabled") is False)

    aja(ENDPOINT, {"status": 200, "content_type": "application/json",
                   "body": json.dumps({"status": "error",
                                       "message": "Taulukko on varattu"})}, testit3)

    print("\n4. HTTP-virhe")

    def testit4(sivu):
        sivu.click("#nakyma-viranomainen")
        sivu.wait_for_timeout(600)
        avaa(sivu, T0)
        sivu.wait_for_selector(".pu-vir-lomake", timeout=5000)
        sivu.click(".pu-lomake-footer button")
        sivu.wait_for_selector(".pu-lomake-viesti.virhe", timeout=5000)
        ok("HTTP 500 näkyy virheenä", "500" in sivu.text_content(".pu-lomake-viesti"),
           sivu.text_content(".pu-lomake-viesti"))

    aja(ENDPOINT, {"status": 500, "body": "palvelinvirhe"}, testit4)

    print("\n5. apps_script_url puuttuu config.json:sta")

    def testit5(sivu):
        ok("Sheets-hakua ei yritetty",
           sivu.evaluate("Object.keys(sheetsLausunnot).length") == 0)
        sivu.click("#nakyma-viranomainen")
        sivu.wait_for_timeout(600)
        avaa(sivu, T0)
        sivu.wait_for_selector(".pu-vir-lomake", timeout=5000)
        ok("Tallenna-nappi pois käytöstä",
           sivu.eval_on_selector(".pu-lomake-footer button", "e => e.disabled") is True)
        ok("syy kerrotaan käyttäjälle",
           "apps_script_url" in sivu.text_content(".pu-lomake-viesti"))
        ok("lomake näyttää GeoJSONin arvot kun Sheets ei käytössä",
           sivu.input_value(".pu-vir-lomake textarea").startswith("Arvokas pihapiiri"))

    aja("", {"status": 200, "body": "{}"}, testit5)

    # ══ 6. Datan lähde: Pages ensin, raw varalla ══════════════════
    # Pages tyhjentää välimuistinsa deployssa, raw pitää tiedostoa 5 min.
    print("\n6. Datan lähde ja välimuistin ohitus")
    tulos6 = testaa_datan_lahde(base, data, virheet)
    for nimi, ehto, lisa in tulos6:
        ok(nimi, ehto, lisa)

    if virheet:
        print("\nKonsolivirheet:")
        for v in virheet:
            print(f"  ! {v}")
    return 0 if all(tulokset) and not virheet else 1


if __name__ == "__main__":
    koodi = main()
    print()
    print("=" * 60)
    if koodi == 0:
        print(f"  KAIKKI OK  ({len(tulokset)} väittämää)")
    else:
        print(f"  {tulokset.count(False)}/{len(tulokset)} VÄITTÄMÄÄ EPÄONNISTUI")
    print("=" * 60)
    raise SystemExit(koodi)
