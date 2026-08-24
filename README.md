# maasto — Rakennusdokumentoinnin pipeline

Kenttäkuvista GitHub Pages -karttasivuksi. Käytössä QGIS, QField ja Python.

> **Päivittäinen käyttö:** [KAYTTOOHJE.md](KAYTTOOHJE.md) — mikä ajetaan omalta
> koneelta, mikä katsotaan GitHubista, työskentely erissä ja vianetsintä.
> Tämä tiedosto kuvaa ensiasennuksen.

## Repon rakenne

```
maasto/
├── docs/                          ← GitHub Pages
│   ├── index.html                 ← juurisivu (?projekti=nimi)
│   ├── [projekti]/index.html      ← projektin oma sivu, pipeline luo
│   ├── kartta.js                  ← kaikki karttalogiikka (jaettu)
│   ├── kartta.css                 ← tyylit (jaettu)
│   ├── config.js                  ← commitoidaan: Pages tarvitsee sen (ks. MML-avain)
│   └── config.example.js          ← pohja config.js:lle
│
├── systeem/
│   ├── taustarasterit/
│   └── rajat/
│
├── projektit/
│   └── heinlansi/
│       ├── config.json            ← WMS-tasot, näytettävät sarakkeet, Sheets-ID
│       ├── data/kohteet.geojson   ← pipeline.py tuottaa
│       ├── data/kasitellyt.json   ← duplikaattikirjanpito
│       └── kuvat/                 ← nimetyt kenttäkuvat
│
├── credentials/                   ← EI gitiin: OAuth-tunnistetiedot
│   ├── oauth_client.json
│   └── drive_token.json           ← auth_pipeline.py luo
│
├── pipeline.py                    ← päätyökalu
├── auth_pipeline.py               ← kertaluonteinen Google-kirjautuminen
├── viranomainen_apps_script.gs    ← Apps Script -endpoint (deployataan käsin)
├── test_pipeline.py               ← testit, ks. KAYTTOOHJE.md
├── test_tila3.py
├── test_kartta.py
├── test_sheets_live.py
├── .gitignore
├── KAYTTOOHJE.md
└── README.md
```

---

## Käyttöönotto

### 1. Kloonaa repo

```bash
git clone https://github.com/MarkusHytonenPD/maasto.git
cd maasto
```

### 2. Luo config.js

```bash
cp docs/config.example.js docs/config.js
```

Avaa `docs/config.js` tekstieditorissa ja täytä alla olevat arvot.

### 3. MML API-avain

1. Kirjaudu OmaTiliin: [API-avaimen ohje](https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje)
2. Luo uusi API-avain (tuote: Karttakuva, taustakartta, maastokartta)
3. Lisää avain `config.js`:n `MML_API_KEY`-kenttään

**Avain on julkinen, eikä sitä voi piilottaa.** Kartta piirretään selaimessa, joten
avain lähtee jokaisessa karttaruutupyynnössä ja on luettavissa kehittäjätyökaluista.
`config.js` on siksi commitoitu — GitHub Pages tarjoilee `docs/`-kansion suoraan
repostosta, eikä ilman tiedostoa julkaistu sivu toimisi. MML:n avaimille ei voi
asettaa verkkotunnus- tai viittaajarajausta; OmaTilissä avaimen voi vain luoda ja
poistaa. Käytännön suojaus on siis:

- **Oma avain per sovellus.** Älä käytä samaa avainta useassa julkaisussa, jotta
  yhden avaimen poistaminen ei kaada muita.
- **Vaihda avain jos se joutuu väärinkäyttöön:** luo uusi avain OmaTilissä, päivitä
  `docs/config.js`, pushaa, ja poista vanha avain. Vanha avain jää git-historiaan,
  mutta poistettu avain ei toimi, joten historian siivoaminen ei ole tarpeen.
- Avoimet rajapinnat ovat maksuttomia; avain on MML:lle käytön seurantaa varten.

### 4. Google — viranomaislausunnot

Viranomainen kirjaa luokituksensa ja kommenttinsa suoraan karttasivulla. Tiedot
menevät projektikohtaiseen Google Sheetiin Apps Script -endpointin kautta, eikä
viranomainen tarvitse Google-tiliä. Pipeline hakee ne takaisin julkisena CSV:nä.

#### 4.1 Drive-kansio

Luo Driveen kansio johon projektien Sheetit syntyvät, ja kopioi sen ID URL:sta
(`drive.google.com/drive/folders/**[ID]**`) `pipeline.py`:n `DRIVE_KANSIO_ID`-vakioon.

> **Pidä kansion linkkijako *Rajoitettu*-tilassa.** Driven jakoasetus periytyy
> kansioon luotaviin tiedostoihin, eikä perittyä oikeutta voi laskea
> tiedostotasolla — Google vastaa `cannotModifyInheritedPermission`. Jos kansio
> on jaettu linkillä muokkausoikeudella, jokainen viranomaislausuntojen Sheet on
> julkisesti **muokattava**: kuka tahansa linkin saanut voisi kirjoittaa
> lausuntoja ohi endpointin. Pipeline varoittaa tästä joka ajolla.

#### 4.2 Kertaluonteinen kirjautuminen

```bash
python3 auth_pipeline.py
```

Selain avautuu — valitse tili jonka haluat **omistavan** luodut Sheetit
(luontevimmin sama tili joka omistaa Drive-kansion). Token tallentuu
`credentials/drive_token.json`:iin, joka on `.gitignore`ssa.

> **Miksi OAuth eikä service account:** service accountilla ei ole omaa Drive-
> tallennustilaa, joten se ei voi omistaa tiedostoja. Luonti kaatuu virheeseen
> *"The user's Drive storage quota has been exceeded"* myös jaettuun kansioon.
> Shared Drive korjaisi tämän, mutta vaatii Google Workspace -tilin.

#### 4.3 Sheetin luonti

Pipeline luo Sheetin automaattisesti projektin ensimmäisellä ajolla: nimi
`Viranomaislausunnot_[projekti]`, välilehti `Lausunnot`, otsikkorivi
`tunnus | taho | luokitus_vir | kommentti_vir | nimi_vir`. Sheet jaetaan
lukuoikeudella linkin tietäville (CSV-hakua varten) ja kirjoitusoikeudella
`SHEET_JAKO_EMAILIT`-vakion osoitteille. `sheets_id` tallentuu projektin
`config.json`:iin, joten Sheet luodaan vain kerran per projekti.

#### 4.4 Apps Script -endpoint (kerran per projekti)

Tehdään vasta kun pipeline on luonut Sheetin (kohta 4.3) — skripti liitetään
Sheetin sisään, joten Sheetin pitää olla olemassa.

**1. Avaa Sheet.** Pipeline tulostaa URL:n muodossa
`https://docs.google.com/spreadsheets/d/[ID]/edit`. Varmista selaimen oikeasta
yläkulmasta että olet kirjautunut tilillä jolla on **muokkausoikeus** Sheetiin
(pipeline jakaa sen `SHEET_JAKO_EMAILIT`-osoitteille). Väärällä tilillä
Laajennukset-valikko on harmaana.

**2. Laajennukset → Apps Script.** Avautuu uusi välilehti, projektin nimenä
Sheetin nimi. Editorissa on tiedosto `Code.gs` ja siinä tyhjä `myFunction()`.

**3. Korvaa koodi.** Klikkaa editoriin, **Ctrl+A** ja **Delete**, liitä sitten
`viranomainen_apps_script.gs`:n koko sisältö. Skripti kirjoittaa yhden rivin per
**(tunnus, taho)**, ja hyväksyy vain tahot `LVV`, `Vastuumuseo` ja
`Maakuntaliitto` — sama lista kuin `kartta.js`:n ja `pipeline.py`:n `TAHOT`. Älä muuta `SPREADSHEET_ID`-vakiota
— se jätetään tyhjäksi, koska skripti on sidottu tähän Sheetiin ja löytää sen
itse.

**4. Tallenna** (levykeikoni tai Ctrl+S). Jos projektin nimeä kysytään, mikä
tahansa nimi kelpaa.

**5. Ota käyttöön → Uusi käyttöönotto** (*Deploy → New deployment*).
Klikkaa **Valitse tyyppi** -kohdan rataskuvaketta ja valitse **Verkkosovellus**
(*Web app*). Täytä:

| Kenttä | Arvo |
|---|---|
| Kuvaus | esim. `v1` |
| Suorita sovelluksena | **Minä** (oma osoitteesi) |
| Kenellä on käyttöoikeus | **Kaikki** |

> **"Kaikki" on eri asia kuin "Kaikki, joilla on Google-tili".** Viranomainen ei
> kirjaudu mihinkään, joten väärä valinta tuottaa kartalla virheen
> *Tallennus epäonnistui: HTTP 401*.

**6. Ota käyttöön.** Ensimmäisellä kerralla Google pyytää valtuutuksen:
*Valtuuta käyttöoikeus* → valitse tili → näyttöön tulee **"Google ei ole
vahvistanut tätä sovellusta"** → **Lisäasetukset** → **Siirry projektiin
(ei turvallinen)** → **Salli**. Varoitus on normaali omalle skriptille.

**7. Kopioi verkkosovelluksen URL.** Se päättyy **`/exec`**:
`https://script.google.com/macros/s/AKfycb.../exec`

> Älä käytä `/dev`-osoitetta — se toimii vain sinulle kirjautuneena.

**8. Testaa endpoint** avaamalla `/exec`-osoite selaimen välilehdellä. Oikea
vastaus on JSON:
> `{"status":"ok","rivit":[]}`
>
> Jos näet HTML-virhesivun tai kirjautumispyynnön, kohta 5 on väärin — korjaa
> käyttöoikeus ja tee **uusi** käyttöönotto.

**9. Lisää URL projektin configiin** ja pushaa:

```bash
# projektit/[projekti]/config.json
"apps_script_url": "https://script.google.com/macros/s/AKfycb.../exec"

git add projektit/[projekti]/config.json
git commit -m "Lisää apps_script_url: [projekti]"
git push
```

Kartta lukee configin `docs/[projekti]/`-kopiosta, joten **aja pipeline loppuun
tai kopioi käsin** — ilman pushia ja kopiota muutos ei näy. Kun URL on
paikallaan, viranomaisen Tallenna-nappi aktivoituu; siihen asti se on harmaana
ja kertoo syyn.

#### 4.5 Vaihtoehto: erillinen skripti (kun Laajennukset-valikko ei toimi)

Jos *Laajennukset → Apps Script* päätyy Driven virhesivulle **"Tiedostoa ei voi
avata juuri nyt"**, syy on yleensä monen Google-tilin sessio: selaimen oletustili
(`/u/0`) ei ole se tili jolla on oikeus skriptiprojektiin. Kaksi ulospääsyä:

- **Yksityinen ikkuna** ja kirjautuminen *vain* Sheetin omistavalle tilille.
- **Erillinen (standalone) skripti** millä tahansa tilillä, jolla on
  muokkausoikeus Sheetiin: avaa **script.new**, liitä
  `viranomainen_apps_script.gs`, ja aseta Sheetin ID:

  ```js
  const SPREADSHEET_ID = "[sheets_id projektin config.json:sta]";
  ```

  Loput kohdista 4–9 samoin. Tämä on ainoa kohta jossa `SPREADSHEET_ID` täytetään
  — sidotussa skriptissä se jää tyhjäksi.

> Endpointin voi testata komentoriviltä. Huomaa ettei POSTissa käytetä
> `-X POST`:ia: `/exec` vastaa 302:lla, ja `-X` pakottaisi POSTin myös
> redirectiin, jolloin vastaus on HTTP 405 vaikka kirjoitus onnistui.
>
> ```bash
> curl -sL "$URL"                                    # → {"status":"ok","rivit":[]}
> curl -sL -H "Content-Type: text/plain;charset=UTF-8" \
>      -d '{"tunnus":"TESTI","luokitus_vir":"paikallinen"}' "$URL"
> ```

> **Jos muutat skriptin koodia myöhemmin**, pelkkä tallennus ei riitä:
> **Ota käyttöön → Hallinnoi käyttöönottoja** → kynäkuvake → **Versio: Uusi
> versio** → *Ota käyttöön*. Näin `/exec`-osoite pysyy samana eikä configia
> tarvitse päivittää. Kokonaan uusi käyttöönotto antaisi **uuden URL:n**, joka
> pitäisi vaihtaa configiin.

### 5. GitHub Pages

Repossa: **Settings → Pages → Source: Deploy from a branch**  
Branch: `main`, kansio: `/docs`

Sivusto julkaistuu osoitteessa `https://MarkusHytonenPD.github.io/maasto/`

### 6. Python-riippuvuudet

```bash
pip install geopandas pillow pyproj gpxpy piexif pandas requests
pip install google-api-python-client google-auth google-auth-oauthlib
pip install tzdata   # vain Windows
```

Google-kirjastoja tarvitaan vain Sheetin luontiin (kohta 4). Ilman niitä muut
tilat toimivat normaalisti — pipeline kertoo puuttuvasta kirjastosta eikä kaadu.

Testejä varten lisäksi (valinnainen):

```bash
pip install playwright && playwright install chromium
```

### 7. pipeline.py — polku ja ajo

Aseta `pipeline.py`:n alusta repon polku omalle koneelle:

```python
REPO_POLKU = Path("/home/markus/omat-apit/rak_kult_kuvakarttajulkaisu")
# Windows: Path(r"C:\GIS\maasto")
```

Projektia **ei** aseteta tiedostoon — pipeline kysyy sen käynnistyessään, samoin
GeoPackagen, layer-nimen, tilan ja näytettävät sarakkeet. Uusi projektinimi luo
projektin rakenteineen.

```bash
python3 pipeline.py
```

| Tila | Tekee |
|---|---|
| `1` | Pipeline: geotägäys → kuvien nimeäminen → push → GeoJSON-vienti → push |
| `2` | Sijoita käsin: yksittäisiä kuvia tunnukselle |
| `3` | Päivitä luokitukset GeoPackageen: kaavoittajan GeoJSON + viranomaisen lausunnot Sheetsistä |

Päivittäinen käyttö ja tilojen yksityiskohdat: [KAYTTOOHJE.md](KAYTTOOHJE.md).

### 8. Testit

```bash
python3 test_pipeline.py             # kuvien nimeäminen, GPX, duplikaattikirjanpito
python3 test_tila3.py                # GeoPackage-päivitys, QGIS-tyylien säilyminen
python3 test_kartta.py               # karttasovellus oikeassa selaimessa
python3 test_sheets_live.py --live   # Sheets-integraatio; LUO ja poistaa oikean Sheetin
```

---

## Huomioita

### WMS-taso ja CORS

Kaavarasteri haetaan Ubigun GeoServeristä WMS-rajapinnalla. Jos selain estää
kutsun GitHub Pagesista (CORS-virhe konsolissa), GeoServeriin täytyy lisätä
`Access-Control-Allow-Origin: *` -headeri. Tämä tehdään Ubigun ylläpidon kautta.
Karttasivu toimii muuten normaalisti — vain kaavarasteri jää näkymättä.

### GPX-aikavyöhyke

BasicAirData GPS Logger (Android) tallentaa GPX-ajat UTC:nä (`Z`-suffiksi).
`pipeline.py` muuntaa ajat automaattisesti Helsingin paikalliseksi ajaksi,
joten `aikaero_min`-kenttään syötetään vain kameran kellodrifti (yleensä 0).

### Työskentely erissä

Kuvia ja GPS-lokeja kertyy tyypillisesti useassa erässä. Pipelinen voi ajaa
saman projektin päälle niin monta kertaa kuin haluaa:

- **Kuvanumerointi jatkuu** siitä mihin edellinen ajo jäi (`ky_15_kuva1` →
  `ky_15_kuva2`), ja `kohteet.geojson` rakennetaan joka ajolla koko
  `kuvat/`-kansiosta — vanhat kuvat säilyvät linkeissä. Rakennusta kohti
  mahtuu edelleen 3 kuvaa.
- **Sama kuva ei kopioidu kahdesti.** Käsitellyt lähdekuvat kirjataan
  tiedostoon `projektit/[projekti]/data/kasitellyt.json` (tunniste =
  tiedostonimi + EXIF-kuvausaika, joka ei muutu geotägäyksessä). Jos sama kuva
  on vahingossa mukana toisessakin ajossa, se ohitetaan merkinnällä
  `↺ ... käsitelty jo aiemmin`.
- **Kuvan korvaaminen:** poista kohdetiedosto `kuvat/`-kansiosta ja aja
  uudelleen — kirjanpito tunnistaa kohteen kadonneeksi ja päästää kuvan läpi.
- **Käsin sijoittelu** kirjaa lisäykset samaan kirjanpitoon, mutta ei estä
  saman kuvan lisäämistä uudelleen — se on tietoinen valinta.

Kirjanpito koskee vain sen käyttöönoton jälkeen ajettuja eriä; ennen sitä
lisätyt kuvat eivät ole tiedostossa, joten vanhan kuvakansion ajaminen
uudelleen tuottaisi niistä yhä duplikaatit.

### Useita GPX-lokeja samalla ajolla

GPS-loggeria ei kannata pitää päällä esimerkiksi yöllä, joten lokeja syntyy
monta. Pipeline kysyy GPX:t rivi kerrallaan — voit antaa useita tiedostoja tai
kansion, jolloin siitä otetaan kaikki `.gpx`-tiedostot. Pisteet yhdistetään
aikajärjestykseen ja päällekkäiset aikaleimat karsitaan.

Lokien väliin jää aukkoja (loggeri pois päältä). Pipeline **ei interpoloi
pitkien aukkojen yli**: jos peräkkäisten GPX-pisteiden väli ylittää annetun
rajan (oletus 10 min, kysytään ajon alussa), aukkoon osuva kuva ohitetaan
varoituksella sen sijaan että se saisi keksityn sijainnin lokien väliltä.
Havaitut aukot listataan ajon alussa.

### Useampi projekti

Anna pipelinelle uusi projektinimi — se luo `projektit/[nimi]/`-rakenteen,
`config.json`-pohjan, `docs/[nimi]/index.html`:n ja viranomaislausuntojen
Sheetin sekä pushaa ne. Käsin jää vain WMS-tasojen lisäys `config.json`:iin ja
Apps Script -deployaus (kohta 4.4).

`docs/kartta.js`, `kartta.css` ja `config.js` ovat yhteisiä kaikille
projekteille; kaikki projektikohtainen on `projektit/[nimi]/config.json`:issa.

### Luokitusasteikko

Kaavoittaja ja viranomainen käyttävät samaa kolmiportaista asteikkoa. Kartta
näyttää selitteet, data säilyy merkkijonoina kuten QGIS-projektissa:

| Kartalla | `potentiaali` / `luokitus_vir` | Väri |
|---|---|---|
| Ei merkintää | tyhjä tai `ei arvoja` | harmaa |
| Suositus säilyttämisestä | `paikallinen` | sininen |
| Suojelukohde | `suojelukohde` | punainen |

Kaavoittajan sarake on `potentiaali` (`pipeline.py`:n `LUOKITUS_SARAKE`);
karttasivulla se esitetään otsikolla *Kaavoittajan suositus*.

### Tila 3 ja QGIS-tyylit

Luokitusten päivitys GeoPackageen tehdään SQLitellä paikan päällä, ei
`to_file()`-kirjoituksella. Syy: uudelleenkirjoitus pudottaisi samaan
GeoPackageen tallennetut QGIS-tyylit (`layer_styles`) ja muut tasot. Uudella
nimellä tallennettaessa tiedosto kopioidaan ensin, joten tyylit säilyvät myös
kopiossa. `test_tila3.py` vahtii tätä.
