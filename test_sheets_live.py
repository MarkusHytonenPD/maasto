"""
Live-testi Google Sheets -integraatiolle.

VAROITUS: tämä testi tekee oikeita muutoksia Driveen — se luo Sheetin
nimellä "Viranomaislausunnot_ZZ_livetesti" kansioon DRIVE_KANSIO_ID ja
POISTAA sen lopuksi. Muita tiedostoja se ei koske.

Siksi testi ei käynnisty vahingossa: tarvitset --live-lipun.

Kattaa:
  • luo_projekti_sheet: välilehden nimi, otsikkorivi, oikeudet, config.json
  • hae_viranomaisdata: julkinen CSV-haku ilman autentikointia
  • skandit, lainausmerkit ja rivinvaihdot Sheetsin ja pipelinen välillä
  • gviz:n ylimääräiset tyhjät sarakkeet
  • otsikkotarkistus (ainoa suoja väärän välilehden lukemiselta)

Vaatii kertaluonteisen kirjautumisen:
    python3 auth_pipeline.py

Ajo:
    python3 test_sheets_live.py --live
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import pipeline as P

PROJEKTI = "ZZ_livetesti"

RIVIT = [
    ["63", "suojelukohde", 'Arvokas pihapiiri, "erittäin" hyvä — kunto ok',
     "Äiti Öllönen", "Museovirasto"],
    ["60", "paikallinen", "Rivinvaihto\nkommentissa", "Test Person", "ELY-keskus"],
    ["", "suojelukohde", "Tyhjä tunnus — pitää ohittaa", "Ei ketään", "Ei virastoa"],
]

tulokset = []


def ok(nimi, ehto, lisa=""):
    tulokset.append(bool(ehto))
    merkki = "OK  " if ehto else "FAIL"
    print(f"  {merkki} {nimi}" + (f" — {lisa}" if lisa else ""))


def main():
    if "--live" not in sys.argv:
        print(__doc__)
        print("Ei ajettu: puuttuu --live.")
        return 0

    if not P.OAUTH_TOKEN.is_file():
        print(f"OHITETTU: kirjautumista ei ole tehty ({P.OAUTH_TOKEN} puuttuu)")
        print("  Aja ensin: python3 auth_pipeline.py")
        return 0

    from googleapiclient.discovery import build

    P.PROJEKTI = PROJEKTI
    P.PROJEKTI_POLKU = Path(tempfile.mkdtemp(prefix="sheets-testi-"))
    P.DATA_POLKU = P.PROJEKTI_POLKU / "data"

    print("1. Sheetin luonti")
    sheets_id = P.luo_projekti_sheet(PROJEKTI)
    if not sheets_id:
        print("  FAIL luonti epäonnistui — ks. viesti yllä")
        return 1

    creds  = P._google_creds()
    drive  = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    try:
        cfg = P._lue_projekticonfig()
        ok("sheets_id config.json:iin", cfg.get("sheets_id") == sheets_id)
        ok("välilehden nimi config.json:iin",
           cfg.get("sheets_valilehti") == P.SHEET_VALILEHTI)
        ok("apps_script_url-paikanvaraaja", cfg.get("apps_script_url") == "")

        meta = sheets.spreadsheets().get(spreadsheetId=sheets_id).execute()
        ok("Sheetin nimi", meta["properties"]["title"] == f"Viranomaislausunnot_{PROJEKTI}",
           meta["properties"]["title"])
        valilehti = meta["sheets"][0]["properties"]
        ok("välilehden nimi", valilehti["title"] == P.SHEET_VALILEHTI, valilehti["title"])
        ok("otsikkorivi kiinnitetty",
           valilehti["gridProperties"].get("frozenRowCount") == 1)
        otsikot = sheets.spreadsheets().values().get(
            spreadsheetId=sheets_id, range=f"{P.SHEET_VALILEHTI}!A1:E1"
        ).execute().get("values", [[]])[0]
        ok("otsikot", otsikot == P.SHEET_OTSIKOT, otsikot)

        oikeudet = drive.permissions().list(
            fileId=sheets_id, fields="permissions(type,role,emailAddress)"
        ).execute()["permissions"]
        julkinen = next((p for p in oikeudet if p["type"] == "anyone"), None)
        ok("julkinen oikeus on olemassa (CSV-haku)", julkinen is not None)
        if julkinen and julkinen["role"] != "reader":
            print(f"  HUOM  linkin tietävillä on '{julkinen['role']}' — Drive-kansion")
            print("        jakoasetus periytyy. Ks. varoitus pipelinen tulosteessa.")
        # anyone-oikeudella ei ole sähköpostia — se karsitaan pois
        kirjoittajat = {p["emailAddress"] for p in oikeudet
                        if p["role"] == "writer" and p.get("emailAddress")}
        ok("kirjoitusoikeus omille osoitteille",
           set(P.SHEET_JAKO_EMAILIT) <= kirjoittajat, sorted(kirjoittajat))

        print("\n2. Julkinen CSV-haku")
        sheets.spreadsheets().values().update(
            spreadsheetId=sheets_id, range=f"{P.SHEET_VALILEHTI}!A2",
            valueInputOption="RAW", body={"values": RIVIT}).execute()

        data = P.hae_viranomaisdata()
        ok("kelvolliset rivit (tyhjä tunnus ohitettu)", set(data) == {"63", "60"},
           sorted(data))
        ok("skandit ja lainausmerkit säilyivät",
           data.get("63", {}).get("kommentti_vir")
           == 'Arvokas pihapiiri, "erittäin" hyvä — kunto ok',
           data.get("63", {}).get("kommentti_vir"))
        ok("nimen skandit", data.get("63", {}).get("nimi_vir") == "Äiti Öllönen")
        ok("rivinvaihto kommentissa",
           "\n" in data.get("60", {}).get("kommentti_vir", ""))
        ok("vain viranomaissarakkeet (gviz:n tyhjät karsittu)",
           set(data["63"]) == set(P.VIRANOMAIS_SARAKKEET), sorted(data["63"]))

        print("\n3. Otsikkotarkistus")
        # gviz palauttaa tuntemattomasta sheet-nimestä ensimmäisen välilehden,
        # joten otsikkotarkistus on ainoa suoja väärän datan lukemiselta
        cfg["sheets_valilehti"] = "EiOleTätä"
        P._kirjoita_projekticonfig(cfg)
        ok("tuntematon välilehti: haku ei hajoa",
           set(P.hae_viranomaisdata()) == {"63", "60"})
        cfg["sheets_valilehti"] = P.SHEET_VALILEHTI
        P._kirjoita_projekticonfig(cfg)

        sheets.spreadsheets().values().update(
            spreadsheetId=sheets_id, range=f"{P.SHEET_VALILEHTI}!A1",
            valueInputOption="RAW",
            body={"values": [["aivan", "muut", "otsikot", "tässä", "nyt"]]}).execute()
        ok("väärät otsikot → tyhjä tulos, ei väärää dataa",
           P.hae_viranomaisdata() == {})

    finally:
        print("\n4. Siivous")
        try:
            drive.files().delete(fileId=sheets_id).execute()
            print(f"  Testi-Sheet poistettu: {sheets_id}")
        except Exception as e:
            print(f"  ⚠ Poisto epäonnistui, poista käsin: {sheets_id} ({e})")

    return 0 if all(tulokset) else 1


if __name__ == "__main__":
    koodi = main()
    if tulokset:
        print()
        print("=" * 60)
        if koodi == 0:
            print(f"  KAIKKI OK  ({len(tulokset)} väittämää)")
        else:
            print(f"  {tulokset.count(False)}/{len(tulokset)} VÄITTÄMÄÄ EPÄONNISTUI")
        print("=" * 60)
    raise SystemExit(koodi)
