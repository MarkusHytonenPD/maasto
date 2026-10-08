"""
Kioski-tietojen tuonti karttaan.

Lukee KIOSKI 3.0 -kohdesivuja, jotka on tallennettu selaimesta
(Ctrl+S, "Verkkosivu, vain HTML"), ja kirjoittaa niiden oleelliset
tiedot projektin tiedostoon data/kioski.json. Kartta näyttää ne kohteen
popupissa omana osionaan. Tiedosto kopioidaan myös docs/[projekti]/data/:iin.

Kohdesivu yhdistetään inventoinnin kohteeseen nimen perusteella
(lähin nimi kohteet.geojsonissa). Jos nimi ei osu, tunnuksen voi antaa
itse muodossa TUNNUS=TIEDOSTO.

    python kioski_tuonti.py heinlansi_rak_kulttuuri sivu1.html sivu2.html
    python kioski_tuonti.py heinlansi_rak_kulttuuri 7=huvila.html

Aiemmin tuodut kohteet säilyvät; saman tunnuksen uusi tuonti korvaa vanhan.
"""

import difflib
import html
import json
import re
import shutil
import sys
from pathlib import Path

REPO_POLKU = Path(__file__).resolve().parent
KIOSKI_URL = "https://www.kulttuuriymparisto.fi/sovellus/asp/k3/k31_kohde_det.aspx?KOHDE_ID={}"

# Tekstiosiot, jotka otetaan mukaan, ja niiden avain kioski.jsonissa.
# Muut osiot (Muu tieto, Seuranta, ...) jätetään pois.
TEKSTIOSIOT = {
    "Kuvaus":         "kuvaus",
    "Historia":       "historia",
    "Suojelutilanne": "suojelutilanne",
    "Arviointi":      "arviointi",
    "Lähteet":        "lahteet",
}

# Pienin nimien samankaltaisuus, jolla kohdistus hyväksytään automaattisesti
KYNNYS = 0.6


def _teksti(fragmentti: str) -> str:
    """HTML-pätkä tekstiksi: <br> rivinvaihdoiksi, tagit pois, välit siistiksi."""
    t = re.sub(r"(?i)<br\s*/?>", "\n", fragmentti)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")
    rivit = [re.sub(r"[ \t]+", " ", r).strip() for r in t.splitlines()]
    # Peräkkäiset tyhjät rivit yhdeksi kappalevaihdoksi
    return re.sub(r"\n{3,}", "\n\n", "\n".join(rivit)).strip()


def jasenna(sivu: str) -> dict:
    """Poimii yhden Kioski-kohdesivun tiedot."""
    tulos = {}

    m = re.search(r"k31_kohde_det\.aspx\?KOHDE_ID=(\d+)", sivu)
    if not m:
        raise ValueError("sivulta ei löydy KOHDE_ID:tä — onko tämä Kioskin kohdesivu?")
    tulos["kohde_id"] = int(m.group(1))
    tulos["url"] = KIOSKI_URL.format(tulos["kohde_id"])

    m = re.search(r'>Nimi:</td>\s*<td[^>]*>(.*?)</td>', sivu, re.S)
    tulos["nimi"] = _teksti(m.group(1)) if m else ""
    m = re.search(r'>Osoite:\s*</td>\s*<td[^>]*>(.*?)</td>', sivu, re.S)
    tulos["osoite"] = _teksti(m.group(1)) if m else ""

    # Valtakunnalliset inventoinnit (RKY, VAMA): rivit otsikon ja seuraavan
    # taulukon välissä
    m = re.search(r'>Valtakunnalliset inventoinnit</td>(.*?)</table>', sivu, re.S)
    if m:
        rivit = [_teksti(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        tulos["valtakunnalliset"] = [r for r in rivit if r]

    # Arvottaminen: arvot ja merkittävyys
    m = re.search(r'>Arvottaminen</td>(.*?)>Ajoitukset</td>', sivu, re.S)
    if m:
        lohko = _teksti(m.group(1))
        arvot = re.findall(r"Arvo:\s*(.+)", lohko)
        merk = re.findall(r"merkittävyys:\s*(.+)", lohko)
        if arvot:
            # Kioski luettelee usean arvon välilyönnein: "rakennushistoriallinen maisemallinen"
            tulos["arvot"] = ", ".join(w for a in arvot for w in a.split())
        if merk:
            tulos["merkittavyys"] = merk[-1].strip()

    # Tekstiosiot: otsikko (img + nimi) ja sen jälkeinen memo-span
    for otsikko, sisalto in re.findall(
            r'class="nakyvyys"[^>]*>(?:&nbsp;|\s)*([^<]+?)\s*</td>.*?'
            r'<span id="memo\d+"[^>]*>(.*?)</span>', sivu, re.S):
        avain = TEKSTIOSIOT.get(html.unescape(otsikko).strip())
        teksti = _teksti(sisalto)
        if not avain or not teksti:
            continue
        # Samaa osiota voi olla useampi (eri lähteistä siirretyt kuvaukset).
        # Pidempi jää voimaan.
        if len(teksti) > len(tulos.get(avain, "")):
            tulos[avain] = teksti

    # Kentät, joilla ei ole arvoa, jätetään pois
    return {k: v for k, v in tulos.items() if v not in ("", [])}


def kohdista(nimi: str, kohteet: dict) -> tuple:
    """Palauttaa (tunnus, samankaltaisuus) lähimmälle nimelle."""
    paras, pisteet = None, 0.0
    a = " ".join(re.findall(r"[a-zåäö0-9]+", nimi.lower()))
    for tunnus, knimi in kohteet.items():
        b = " ".join(re.findall(r"[a-zåäö0-9]+", knimi.lower()))
        s = difflib.SequenceMatcher(None, a, b).ratio()
        # Kioskin nimi on usein inventoinnin nimen osa ("Koukunpolvi, X")
        if a and a in b:
            s = max(s, 0.9)
        # Sanatason osuma kestää kirjoitusasun eroja (Forsblom/Forsbom)
        sa, sb = set(a.split()), set(b.split())
        if sa and sb:
            s = max(s, sum(difflib.get_close_matches(w, sb, 1, 0.8) != [] for w in sa) / len(sa))
        if s > pisteet:
            paras, pisteet = tunnus, s
    return paras, pisteet


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    projekti, tiedostot = argv[0], argv[1:]
    proj = REPO_POLKU / "projektit" / projekti
    geo = json.loads((proj / "data" / "kohteet.geojson").read_text(encoding="utf-8"))
    kohteet = {str(f["properties"]["tunnus"]): f["properties"].get("nimi") or ""
               for f in geo["features"]}

    kohde_json = proj / "data" / "kioski.json"
    data = json.loads(kohde_json.read_text(encoding="utf-8")) if kohde_json.is_file() else {}

    virheita = 0
    for arg in tiedostot:
        tunnus, _, polku = arg.rpartition("=") if "=" in arg else ("", "", arg)
        try:
            tiedot = jasenna(Path(polku).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as e:
            print(f"  OHITETTU {polku}: {e}")
            virheita += 1
            continue
        if tunnus:
            if tunnus not in kohteet:
                print(f"  OHITETTU {polku}: tunnusta {tunnus} ei ole aineistossa")
                virheita += 1
                continue
        else:
            tunnus, s = kohdista(tiedot["nimi"], kohteet)
            if s < KYNNYS:
                print(f"  EI KOHDISTU {polku}: \"{tiedot['nimi']}\" — lähin {tunnus} "
                      f"\"{kohteet.get(tunnus)}\" ({s:.2f}). Anna tunnus: TUNNUS={polku}")
                virheita += 1
                continue
        data[tunnus] = tiedot
        print(f"  {tunnus:>3} \"{kohteet[tunnus]}\" ← Kioski {tiedot['kohde_id']} \"{tiedot['nimi']}\"")

    data = dict(sorted(data.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0))
    kohde_json.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    docs = REPO_POLKU / "docs" / projekti / "data"
    if docs.is_dir():
        shutil.copy2(kohde_json, docs / "kioski.json")
    print(f"Kirjoitettu {kohde_json.relative_to(REPO_POLKU)}: {len(data)} kohdetta")
    return 1 if virheita else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
