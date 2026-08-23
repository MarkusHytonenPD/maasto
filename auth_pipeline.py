"""
auth_pipeline.py
================
Kertaluonteinen Google-kirjautuminen pipelinelle.

Aja tämä kerran:
    python3 auth_pipeline.py

Selain avautuu — valitse se tili jonka haluat OMISTAVAN luodut Sheetit.
Suositus: markushytonen.tyo@gmail.com, joka omistaa myös Driven
pipeline-kansion johon Sheetit luodaan.

Token tallentuu tiedostoon credentials/drive_token.json, joka on .gitignoressa.
Sen jälkeen pipeline.py hoitaa Sheetien luonnin itsenäisesti — tätä skriptiä
ei tarvitse ajaa uudelleen ellei tokenia poisteta tai peruuteta.

Miksi OAuth eikä service account:
    Service accountilla ei ole omaa Drive-tallennustilaa, joten se ei voi
    omistaa tiedostoja — luonti kaatuu virheeseen "The user's Drive storage
    quota has been exceeded" myös jaetussa kansiossa. Shared Drive korjaisi
    tämän, mutta se vaatii Google Workspace -tilin.

Vaatimukset:
    pip install --user google-auth-oauthlib google-api-python-client
"""

from pathlib import Path

REPO_POLKU    = Path(__file__).resolve().parent
OAUTH_CLIENT  = REPO_POLKU / "credentials" / "oauth_client.json"
OAUTH_TOKEN   = REPO_POLKU / "credentials" / "drive_token.json"

# drive.file riittää: sovellus saa luoda tiedostoja ja hallita vain omia
# luomiaan tiedostoja. Muuhun Driven sisältöön se ei pääse käsiksi.
SCOPET = ["https://www.googleapis.com/auth/drive.file"]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        print(f"VIRHE: Kirjasto puuttuu: {e}")
        print("Asenna: pip install --user google-auth-oauthlib google-api-python-client")
        raise SystemExit(1)

    if not OAUTH_CLIENT.is_file():
        print(f"VIRHE: OAuth-clientia ei löydy: {OAUTH_CLIENT}")
        print("Lataa se Google Cloud Consolesta (OAuth 2.0 Client ID, tyyppi Desktop app)")
        print("ja tallenna yllä olevaan polkuun.")
        raise SystemExit(1)

    if OAUTH_TOKEN.exists():
        vastaus = input(
            f"Token on jo olemassa: {OAUTH_TOKEN}\n"
            "Kirjaudutaanko uudelleen ja korvataan se? (k/e): "
        ).strip().lower()
        if vastaus != "k":
            print("Peruutettu — vanha token jätettiin ennalleen.")
            return

    print("\nSelain avautuu. Valitse tili jonka haluat omistavan luodut Sheetit.")
    print("Jos Google varoittaa vahvistamattomasta sovelluksesta:")
    print("  Lisäasetukset → Siirry sovellukseen (ei turvallinen) → Jatka.\n")

    flow  = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT), SCOPET)
    creds = flow.run_local_server(port=0, prompt="consent")

    OAUTH_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    OAUTH_TOKEN.chmod(0o600)

    print(f"\n✓ Token tallennettu: {OAUTH_TOKEN}")

    # Varmistetaan heti kummalla tilillä kirjauduttiin ja pääseekö Drive-kansioon
    try:
        from googleapiclient.discovery import build

        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        tiedot = drive.about().get(fields="user(emailAddress)").execute()
        print(f"  Kirjautunut tili: {tiedot['user']['emailAddress']}")
        print("\n  Tämä tili omistaa jatkossa luodut Sheetit.")
        print("  Aja seuraavaksi: python3 pipeline.py")
    except Exception as e:
        print(f"  ⚠ Tilin tarkistus epäonnistui: {e}")
        print("    Token on silti tallennettu — kokeile ajaa pipeline.py.")


if __name__ == "__main__":
    main()
