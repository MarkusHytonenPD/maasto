"""
Selaintesti luokitusdemolle (docs/kartta-demo.js, docs/kartta-demo.css).

Ajaa oikean demosivun oikeassa selaimessa (Playwright + Chromium) ja ohjaa
kaikki ulkoiset pyynnöt paikallisiin fikstuureihin, joten testi ei kosketa
MML:ää, Apps Scriptia eikä docs/-kansion tiedostoja.

Kattaa demoversion erot tuotantoon:
  • seitsenportainen asteikko, sama kaavoittajalle ja viranomaiselle
  • tyhjä ei ole valittava luokka — viranomaisella se on "ei kommenttia"
  • Vastuumuseon kanta jokaisen kohteen lähtöarvona
  • museon tyhjä (kartalla musta) → "ei suojeluarvoja / säilymisen edellytyksiä"
  • vanhaa potentiaali-saraketta ei lueta lähtöarvoksi
  • katkoviiva = arvo vielä museon pohjalla, yhtenäinen = oma kirjaus
  • "ei suojeluarvoja" piirtyy mustana pisteenä: täyttö = oma kirjaus
  • kaavoittajan luokitus ja kommentti tallentuvat Sheetiin tahona
    "Kaavoittaja (demo)", ei localStorageen
  • "ei arvoja" ei sekoitu luokkaan "ei_suojeluarvoja"
  • selitelaatikon määrät ja "museon pohjalla" -laskuri
  • ladattu GeoJSON sisältää voimassa olevan luokan jokaiselle kohteelle

Ajo:
    python3 test_kartta_demo.py

Vaatii:
    pip install playwright && playwright install chromium
"""
import base64
import functools
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

REPO  = Path(__file__).resolve().parent
DOCS  = REPO / "docs"
LAHDE = REPO / "projektit" / "heinlansi_rak_kulttuuri" / "data" / "kohteet.geojson"

PROJEKTI = "ZZ_demotesti"
ENDPOINT = "https://apps-script.test/exec"

VARIT = {
    "ei_suojeluarvoja":          "#000000",
    "kumottava":                 "#7570b3",
    "kumoutuva_mk_suojelukohde": "#b05ccc",
    "kumoutuva_suojelukohde":    "#e7298a",
    "paikallinen":               "#1f78b4",
    "suojelukohde":              "#e31a1c",
    "lisatietoja":               "#ff7f00",
}
EI_KIRJAUSTA_VARI = "#555555"
KAAVOITTAJA_TAHO = "Kaavoittaja (demo)"

LAATTA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP4//8/AAX+Av7czFnnAAAAAElFTkSuQmCC")

tulokset = []


def ok(nimi, ehto, lisa=""):
    tulokset.append(bool(ehto))
    print(f"  {'OK  ' if ehto else 'FAIL'} {nimi}" + (f" — {lisa}" if lisa else ""))


class _Kasittelija(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _palvele(kansio: Path):
    class Palvelin(http.server.ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    palvelin = Palvelin(("127.0.0.1", 0),
                        functools.partial(_Kasittelija, directory=str(kansio)))
    threading.Thread(target=palvelin.serve_forever, daemon=True).start()
    return palvelin, palvelin.server_address[1]


def _tyhja(arvo):
    return str(arvo or "").strip().lower() in ("", "ei arvoja", "0", "null", "none", "nan")


def rakenna_docs(base: Path):
    """Kopioi demon tiedostot ja rakentaa testiprojektin oikeasta datasta."""
    pages = base / "docs"
    kohde = pages / PROJEKTI
    (kohde / "data").mkdir(parents=True, exist_ok=True)
    for nimi in ("kartta-demo.js", "kartta-demo.css", "config.js"):
        shutil.copy2(DOCS / nimi, pages / nimi)
    shutil.copy2(DOCS / "heinlansi_demo" / "index.html", kohde / "index.html")
    (kohde / "index.html").write_text(
        (kohde / "index.html").read_text(encoding="utf-8")
        .replace('window.PROJEKTI = "heinlansi_demo"', f'window.PROJEKTI = "{PROJEKTI}"'),
        encoding="utf-8")

    data = json.loads(LAHDE.read_text(encoding="utf-8"))
    (kohde / "data" / "kohteet.geojson").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (kohde / "config.json").write_text(json.dumps({
        "nimi": "Demotesti", "tasot": [],
        "naytettavat_sarakkeet": ["tunnus", "potentiaali", "vuosi", "huom"],
        "apps_script_url": ENDPOINT,
    }, ensure_ascii=False), encoding="utf-8")
    return pages, data


def valitse_kohteet(data):
    """Etsii aineistosta kohteet joilla demon logiikka on testattavissa."""
    loydot = {}
    for f in data["features"]:
        p = data and f["properties"]
        tunnus = str(p.get("tunnus"))
        museo  = "" if _tyhja(p.get("luokitus_museo")) else str(p["luokitus_museo"]).strip()
        pot    = "" if _tyhja(p.get("potentiaali")) else str(p["potentiaali"]).strip()
        if not museo and not pot:
            loydot.setdefault("museo_tyhja", tunnus)
        if museo == "paikallinen":
            loydot.setdefault("museo_paikallinen", tunnus)
        if not museo and pot:
            # Vanha kenttäluokitus jolle museo ei anna tukea
            loydot.setdefault("vanha_potentiaali", (tunnus, pot))
    return loydot


def aja():
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pages, data = rakenna_docs(base)
        kohteet = valitse_kohteet(data)
        for avain in ("museo_tyhja", "museo_paikallinen", "vanha_potentiaali"):
            if avain not in kohteet:
                print(f"Testidataa puuttuu: {avain}")
                return False

        tyhja_t       = kohteet["museo_tyhja"]
        paikallinen_t = kohteet["museo_paikallinen"]
        vanha_t, vanha_arvo = kohteet["vanha_potentiaali"]
        # Kaavoittajalla on jo oma kirjaus tälle kohteelle (Sheetissä)
        oma_t = paikallinen_t

        sheet_rivit = [{
            "tunnus": oma_t, "taho": KAAVOITTAJA_TAHO,
            "luokitus_vir": "kumottava",
            "kommentti_vir": "Jää kumottavalle alueelle",
            "nimi_vir": "Kaavoittaja Testi",
        }]
        postit = []

        palvelin, portti = _palvele(pages)
        juuri = f"http://127.0.0.1:{portti}"
        virheet = []

        with sync_playwright() as pw:
            selain = pw.chromium.launch()
            sivu   = selain.new_page()
            sivu.on("console", lambda m: virheet.append(m.text)
                    if m.type == "error" and "Failed to load resource" not in m.text else None)
            sivu.on("pageerror", lambda e: virheet.append(f"pageerror: {e}"))
            sivu.route("**maanmittauslaitos.fi/**",
                       lambda r, q: r.fulfill(status=200, body=LAATTA, content_type="image/png"))

            def endpoint(route, pyynto):
                if pyynto.method == "POST":
                    postit.append(json.loads(pyynto.post_data))
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"status": "ok", "toiminto": "lisatty"}))
                else:
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"status": "ok", "rivit": sheet_rivit}))
            sivu.route("https://apps-script.test/**", endpoint)

            sivu.goto(f"{juuri}/{PROJEKTI}/index.html", wait_until="load")
            sivu.wait_for_function("window.geojsonData !== null", timeout=15000)
            sivu.wait_for_timeout(300)

            print("\n── Luokka-asteikko ──")
            luokat = sivu.evaluate("LUOKAT.map(l => [l.arvo, l.vari])")
            ok("seitsemän luokkaa", len(luokat) == 7, f"{len(luokat)}")
            ok("arvot ja värit odotetut", dict(luokat) == VARIT, str(dict(luokat)))
            ok("tyhjä ei ole valittava luokka",
               not any(a == "" for a, _ in luokat))
            ok("tyhjän väri tulee EI_KIRJAUSTA:sta, ei mustasta pisteestä",
               sivu.evaluate("luokkaVari('')") == EI_KIRJAUSTA_VARI,
               sivu.evaluate("luokkaVari('')"))
            ok("ei_suojeluarvoja on pistesymboli",
               sivu.evaluate("LUOKAT.find(l => l.arvo === 'ei_suojeluarvoja').piste") is True)
            ok("'ei arvoja' luetaan tyhjäksi, ei ei_suojeluarvoja-luokaksi",
               sivu.evaluate("normalisoiLuokka('ei arvoja')") == ""
               and sivu.evaluate("normalisoiLuokka('ei_suojeluarvoja')") == "ei_suojeluarvoja")

            print("\n── Vastuumuseon kanta lähtöarvona ──")
            def tyyli(tunnus):
                return sivu.evaluate(
                    "t => ({vari: markkerit[t].options.color,"
                    "       katko: markkerit[t].options.dashArray,"
                    "       tayttö: markkerit[t].options.fill,"
                    "       sade: markkerit[t].options.radius})", str(tunnus))

            a = tyyli(tyhja_t)
            ok(f"museon tyhjä → musta piste (kohde {tyhja_t})",
               a["vari"] == VARIT["ei_suojeluarvoja"], a["vari"])
            ok("…pienellä säteellä", a["sade"] == 7, str(a["sade"]))
            ok("…ja täyttämättä, koska omaa kantaa ei ole", a["tayttö"] is False)

            b = tyyli(vanha_t)
            ok(f"vanhaa potentiaalia ei lueta pohjaksi (kohde {vanha_t}, potentiaali={vanha_arvo})",
               b["vari"] == VARIT["ei_suojeluarvoja"], b["vari"])

            c = tyyli(oma_t)
            ok(f"kaavoittajan oma Sheet-kirjaus voittaa museon (kohde {oma_t})",
               c["vari"] == VARIT["kumottava"], c["vari"])
            ok("…ja piirtyy yhtenäisellä viivalla", not c["katko"], str(c["katko"]))

            print("\n── Popup, kaavoittajan näkymä ──")
            sivu.evaluate("t => markkerit[t].openPopup()", str(tyhja_t))
            sivu.wait_for_selector(".pu-vir-lomake .pu-napit button")
            napit = sivu.eval_on_selector_all(
                ".pu-vir-lomake .pu-napit button", "ns => ns.map(n => n.textContent.trim())")
            ok("seitsemän luokituspainiketta", len(napit) == 7, str(len(napit)))
            ok("'Ei merkintää' ei ole valittavissa",
               not any("merkintää" in n for n in napit), str(napit))
            valittu = sivu.eval_on_selector_all(
                ".pu-vir-lomake .pu-napit button.aktiivinen", "ns => ns.map(n => n.textContent.trim())")
            ok("museon pohja on esivalittuna",
               valittu == ["Ei suojeluarvoja / säilymisen edellytyksiä"], str(valittu))
            ok("pohja-arvosta kerrotaan lomakkeella",
               sivu.locator(".pu-pohja-vihje").count() == 1)
            ok("kaavoittajan näkymässä ei lukuarvoriviä",
               sivu.locator(".pu-kaava-luku").count() == 0)
            ok("viranomaisten kommentit näkyvät myös kaavoittajalle",
               sivu.locator(".pu-vir .pu-taho").count() == 3)

            print("\n── Tallennus Sheetiin ──")
            sivu.locator(".pu-vir-lomake .pu-napit button", has_text="Kumottavalla alueella").click()
            sivu.locator(".pu-vir-lomake textarea").fill("Purkualue, ei säilytettävää")
            sivu.locator(".pu-vir-lomake input[type=text]").fill("Markus")
            sivu.locator(".pu-lomake-footer button").click()
            sivu.wait_for_selector(".pu-lomake-viesti.onnistui", timeout=8000)
            ok("POST lähti", len(postit) == 1, str(len(postit)))
            if postit:
                r = postit[-1]
                ok("taho = Kaavoittaja (demo)", r.get("taho") == KAAVOITTAJA_TAHO, str(r.get("taho")))
                ok("tunnus oikein", str(r.get("tunnus")) == str(tyhja_t), str(r.get("tunnus")))
                ok("luokitus mukana", r.get("luokitus_vir") == "kumottava", str(r.get("luokitus_vir")))
                ok("kommentti mukana",
                   r.get("kommentti_vir") == "Purkualue, ei säilytettävää", str(r.get("kommentti_vir")))
            d = tyyli(tyhja_t)
            ok("väri päivittyi heti", d["vari"] == VARIT["kumottava"], d["vari"])
            ok("viiva muuttui yhtenäiseksi", not d["katko"], str(d["katko"]))
            sivu.evaluate("map.closePopup()")

            print("\n── Selitelaatikko ──")
            rivit = sivu.eval_on_selector_all(
                ".selitys-lista li .selitys-teksti", "ns => ns.map(n => n.textContent.trim())")
            ok("seitsemän seliteriviä", len(rivit) == 7, str(len(rivit)))
            maarat = sivu.eval_on_selector_all(
                ".selitys-lista li .selitys-maara", "ns => ns.map(n => Number(n.textContent))")
            ok("määrien summa = kohteiden määrä",
               sum(maarat) == len(data["features"]), f"{sum(maarat)} / {len(data['features'])}")
            pohja_teksti = sivu.locator(".selitys-alaosa").inner_text()
            odotettu_pohja = len(data["features"]) - 2      # oma_t Sheetistä + juuri tallennettu
            ok("museon pohjalla -laskuri", str(odotettu_pohja) in pohja_teksti, pohja_teksti.strip())

            print("\n── Viranomaisnäkymä ──")
            sivu.evaluate("vaihdaNakyma('museo')")
            sivu.evaluate("t => markkerit[t].openPopup()", str(paikallinen_t))
            sivu.wait_for_selector(".pu-vir-lomake")
            ok("sama seitsenportainen asteikko myös viranomaisella",
               sivu.locator(".pu-vir-lomake .pu-napit button").count() == 7)
            ok("kaavoittajan kanta näkyy lukuarvona",
               sivu.locator(".pu-kaava-luku .pu-lukuarvo").inner_text().strip()
               == "Kumottavalla alueella")
            selite = sivu.eval_on_selector_all(
                ".selitys-lista li .selitys-teksti", "ns => ns.map(n => n.textContent.trim())")
            ok("viranomaisnäkymässä on 'Ei kommenttia' -rivi",
               "Ei kommenttia" in selite, str(selite))
            vir_maarat = sivu.eval_on_selector_all(
                ".selitys-lista li .selitys-maara", "ns => ns.map(n => Number(n.textContent))")
            ok("viranomaisnäkymän määrien summa = kohteiden määrä",
               sum(vir_maarat) == len(data["features"]),
               f"{sum(vir_maarat)} / {len(data['features'])}")
            sivu.evaluate("map.closePopup()")
            sivu.evaluate("vaihdaNakyma('kaav')")

            print("\n── Ladattu GeoJSON ──")
            ladattu = sivu.evaluate("""() => {
              const kopio = JSON.parse(JSON.stringify(geojsonData));
              kopio.features.forEach(f => {
                const { arvot } = kaavoittajaKanta(f.properties);
                f.properties.potentiaali    = arvot[LUOKITUS_VIR];
                f.properties.kommentti_kaav = arvot[KOMMENTTI_VIR] || "";
              });
              return kopio.features.map(f => [String(f.properties.tunnus),
                                              f.properties.potentiaali,
                                              f.properties.kommentti_kaav]);
            }""")
            ok("jokaisella kohteella on luokka",
               all(arvo for _, arvo, _ in ladattu), "tyhjiä: " +
               str(sum(1 for _, a, _ in ladattu if not a)))
            ok("tallennettu luokka mukana",
               dict((t, a) for t, a, _ in ladattu)[str(tyhja_t)] == "kumottava")
            ok("kommentti mukana",
               dict((t, k) for t, _, k in ladattu)[str(tyhja_t)] == "Purkualue, ei säilytettävää")
            ok("vanha potentiaali korvautui museon pohjalla",
               dict((t, a) for t, a, _ in ladattu)[str(vanha_t)] == "ei_suojeluarvoja")

            print("\n── Konsoli ──")
            ok("ei JS-virheitä", not virheet, "; ".join(virheet[:3]))

            selain.close()
        palvelin.shutdown()

    laske = len(tulokset)
    hyvaksytyt = sum(tulokset)
    print(f"\n{hyvaksytyt}/{laske} väittämää läpi")
    return hyvaksytyt == laske


if __name__ == "__main__":
    sys.exit(0 if aja() else 1)
