"""
Lausuntokierroksen päättäminen: kirjausten jäädytys.

Hakee Sheetin nykytilan Apps Scriptin kautta (sama haku kuin kartalla) ja
tallentaa sen projektin tiedostoon data/kirjaukset.json. Samalla projektin
config.jsoniin asetetaan "kirjaukset_lukittu": true, jolloin kartta

  • lukee kirjaukset tästä tiedostosta eikä kutsu Apps Scriptiä lainkaan
  • näyttää kaikki lomakkeet harmaana (ei tallennusta)

Tiedostot kopioidaan myös docs/[projekti]/:iin.

    python3 jaadyta_kirjaukset.py heinlansi_rak_kulttuuri

Lukituksen avaaminen: aseta config.json:issa "kirjaukset_lukittu": false
(molemmissa kopioissa). Kartta hakee silloin taas Sheetin tuoreen tilan.
Sheetiin itseensä ei kosketa, joten pipelinen tila 3 toimii ennallaan.
"""

import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_POLKU = Path(__file__).resolve().parent

# Apps Script vastaa välillä 404:llä tai hitaasti — yritetään muutaman kerran
YRITYKSIA = 4
AIKARAJA_S = 90


def hae_rivit(url: str) -> list:
    """Hakee Sheetin rivit. Heittää RuntimeError:n, jos kaikki yritykset epäonnistuvat."""
    virhe = None
    for yritys in range(1, YRITYKSIA + 1):
        try:
            with urllib.request.urlopen(url, timeout=AIKARAJA_S) as vastaus:
                data = json.loads(vastaus.read().decode("utf-8"))
            if data.get("status") != "ok" or not isinstance(data.get("rivit"), list):
                raise ValueError(data.get("message") or "odottamaton vastaus")
            return data["rivit"]
        except Exception as e:      # HTTP-virheet, aikakatkaisu, rikkinäinen JSON
            virhe = e
            print(f"  Yritys {yritys}/{YRITYKSIA} epäonnistui: {e}")
            time.sleep(3)
    raise RuntimeError(f"Sheetin haku epäonnistui: {virhe}")


def main(argv: list) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 1
    projekti = argv[0]
    proj = REPO_POLKU / "projektit" / projekti
    docs = REPO_POLKU / "docs" / projekti
    config_polku = proj / "config.json"
    config = json.loads(config_polku.read_text(encoding="utf-8"))

    url = str(config.get("apps_script_url") or "").strip()
    if not url:
        print("apps_script_url puuttuu config.json:sta — ei mitään jäädytettävää")
        return 1

    try:
        rivit = hae_rivit(url)
    except RuntimeError as e:
        print(f"  {e}")
        return 1

    # Samassa muodossa kuin Apps Scriptin vastaus, jotta kartta lukee sen
    # samalla koodilla
    haettu = datetime.now().astimezone().isoformat(timespec="seconds")
    kirjaukset = {"status": "ok", "haettu": haettu, "rivit": rivit}
    kohde = proj / "data" / "kirjaukset.json"
    kohde.write_text(json.dumps(kirjaukset, ensure_ascii=False, indent=1), encoding="utf-8")

    config["kirjaukset_lukittu"] = True
    config_polku.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")

    if docs.is_dir():
        (docs / "data").mkdir(exist_ok=True)
        shutil.copy2(kohde, docs / "data" / "kirjaukset.json")
        shutil.copy2(config_polku, docs / "config.json")

    sisalto = [r for r in rivit
               if str(r.get("luokitus_vir") or "").strip() or str(r.get("kommentti_vir") or "").strip()]
    tahot = {}
    for r in sisalto:
        tahot[r.get("taho", "")] = tahot.get(r.get("taho", ""), 0) + 1
    print(f"Jäädytetty {kohde.relative_to(REPO_POLKU)}: {len(rivit)} riviä, "
          f"{len(sisalto)} sisällöllistä ({haettu})")
    for taho, n in sorted(tahot.items()):
        print(f"  {taho}: {n}")
    print('Kartan lomakkeet lukittu ("kirjaukset_lukittu": true)')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
