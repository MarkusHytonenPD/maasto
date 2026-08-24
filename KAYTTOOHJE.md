# Käyttöohje — rakennusdokumentoinnin karttajulkaisu

Käytännön ohje päivittäiseen työhön. Ensiasennus (API-avaimet, Apps Script,
GitHub Pages, Python-riippuvuudet) on kuvattu erikseen [README.md](README.md):ssä.

---

## Kokonaiskuva: mikä ajetaan missä

Työnkulku on kolmiosainen: julkaisu, luokittelu selaimessa ja luokitusten
palautus GeoPackageen.

```
  OMA KONE                              GITHUB                      GOOGLE
  ────────                              ──────                      ──────
  kuvat + GPX-lokit                     repo MarkusHytonenPD/maasto
  GeoPackage (QGIS/QField)                  ├── projektit/[projekti]/kuvat/
          │                                 │   └── ky_[tunnus]_kuva1..3.jpg
          ▼                                 ├── projektit/[projekti]/data/
  python3 pipeline.py  ──── git push ──▶    │   └── kohteet.geojson
  tila 1 / 2                                └── docs/  → GitHub Pages
                                                     │
                                                     ▼
                                       https://markushytonenpd.github.io/maasto/[projekti]/
                                                     │
                            kaavoittaja ─────────────┤
                            (luokittelee selaimessa, │
                             lataa GeoJSONin)        │
                                                     └── viranomainen ──▶ Sheet
                                                         (kirjaa lausunnon)   │
          ┌──────────────────────────────────────────────────────────────────┘
          ▼
  python3 pipeline.py  tila 3
  (yhdistää molemmat takaisin GeoPackageen)
```

**Pipeline ajetaan aina omalta koneelta.** Se tarvitsee paikalliset kuvat, GPX-lokit
ja GeoPackagen sekä paikallisen kloonin repostosta — mitään näistä ei ole GitHubissa.
Pipeline hoitaa julkaisun itse: se commitoi ja pushaa tulokset.

**Karttaa katsotaan GitHubista.** Selainsovellus on GitHub Pagesissa eikä katsoja
tarvitse mitään asennettua — pelkkä linkki riittää. Viranomainen ei tarvitse
Google-tiliä: lausunto tallentuu Sheetiin Apps Script -endpointin kautta.

**Luokitukset palaavat GeoPackageen tilassa 3.** Kaavoittajan selainluokitukset
kulkevat ladattuna GeoJSON-tiedostona, viranomaisen lausunnot haetaan Sheetsistä.

---

## Osa A — Pipelinen ajaminen omalta koneelta

### Tarvitset

- kuvakansion (puhelin, drone tai järjestelmäkamera)
- GPX-lokit, jos mukana on järjestelmäkameran kuvia joissa ei ole GPS:ää
- GeoPackagen jossa rakennukset ja `tunnus`-sarake (QGIS/QField-vienti)
- tämän repon paikallisena kloonina, push-oikeudet GitHubiin
- Python-riippuvuudet:
  `pip install geopandas pillow pyproj gpxpy piexif pandas requests`
  `pip install google-api-python-client google-auth google-auth-oauthlib`
- kertaluonteinen Google-kirjautuminen: `python3 auth_pipeline.py`
  (tarvitaan vain viranomaislausuntojen Sheetin luontiin, ks. README kohta 4)

### Ajo

```bash
python3 /home/markus/omat-apit/rak_kult_kuvakarttajulkaisu/pipeline.py
```

Skripti kysyy vuorollaan:

| Kysymys | Selitys |
|---|---|
| **Projekti** | Kansion nimi `projektit/`-hakemistossa. Uusi nimi luo projektin: `config.json`, `docs/[projekti]/index.html`, ja pushaa ne. |
| **GeoPackage-tiedosto** | Polku .gpkg-tiedostoon. Ei kopioida repoon. |
| **Layer-nimi** | Taso GeoPackagen sisällä. |
| **Tila** | `1` = pipeline (automaattinen), `2` = sijoita käsin, `3` = päivitä luokitukset GeoPackageen. |
| **Näytettävät sarakkeet** | Mitkä GeoPackagen sarakkeet näkyvät kartan popupissa. Numerot tai nimet pilkulla eroteltuna, Enter = edellinen valinta (tai kaikki). Valinta tallentuu `config.json`:iin. |
| **Kuvakansio** | Vain tila 1. **Anna kansio jossa on vain tämän erän uudet kuvat.** |
| **Hakuetäisyydet** | Kuinka läheltä rakennusta etsitään: puhelin 60 m, drone 300 m, järj.kamera 300 m. Enter = oletus. |
| **GPX-tiedostoja? (k/e)** | `k` jos mukana on geotägäämättömiä järjestelmäkamerakuvia. |
| **GPX-polut** | Yksi polku per rivi, tai kansio = kaikki sen .gpx-tiedostot. Tyhjä rivi lopettaa. |
| **Kameran kellodrifti** | Minuutteina, yleensä `0`. Aikavyöhyke hoidetaan automaattisesti. |
| **Suurin sallittu GPX-aukko** | Oletus 10 min. Ks. alla. |

Tämän jälkeen ajo etenee itsestään: geotägäys → nimeäminen → kuvien push →
GeoJSON-vienti → datan push → yhteenveto.

### Työskentely erissä

Kuvia otetaan useassa erässä ja GPS-loggeri tuottaa monta lokia (sitä ei kannata
pitää päällä esimerkiksi yöllä). Pipelinen voi ajaa saman projektin päälle niin
monta kertaa kuin haluaa.

**Kuvat.** Numerointi jatkuu siitä mihin edellinen ajo jäi (`ky_15_kuva1` →
`ky_15_kuva2`), ja `kohteet.geojson` rakennetaan joka ajolla koko `kuvat/`-kansiosta,
joten vanhat kuvat säilyvät. Rakennusta kohti mahtuu 3 kuvaa.

**Duplikaatit.** Käsitellyt lähdekuvat kirjataan tiedostoon
`projektit/[projekti]/data/kasitellyt.json`. Jos sama kuva on vahingossa mukana
toisessakin ajossa, se ohitetaan viestillä `↺ ... käsitelty jo aiemmin`. Tunniste on
tiedostonimi + EXIF-kuvausaika, joten se kestää geotägäyksen.

**GPX-lokit.** Anna kaikki kerralla — pisteet yhdistetään aikajärjestykseen ja
päällekkäiset aikaleimat karsitaan. Sama kuvaerä voi siis sisältää usean päivän kuvia.

**Aukot lokeissa.** Kun loggeri on ollut pois päältä, lokien väliin jää aukko.
Pipeline **ei interpoloi pitkien aukkojen yli**: aukkoon osuva kuva ohitetaan sen
sijaan että se saisi keksityn sijainnin illan ja aamun pisteiden väliltä. Raja on
oletuksena 10 min ja kysytään ajon alussa. Havaitut aukot listataan ennen käsittelyä:

```
22 GPX-pistettä ladattu (20.07. 15:00 – 21.07. 09:10)
1 aukkoa yli 10 min — näiden yli ei interpoloida:
  20.07. 15:10 – 21.07. 09:00  (1070 min)
```

**Kuvan korvaaminen.** Poista kohdetiedosto `projektit/[projekti]/kuvat/`-kansiosta ja
aja uudelleen — kirjanpito tunnistaa kohteen kadonneeksi ja päästää kuvan läpi.

> Kirjanpito otettiin käyttöön 27.7.2026. Sitä ennen lisätyt kuvat eivät ole
> tiedostossa, joten vanhan kuvakansion ajaminen uudelleen duplikoisi ne yhä.

### Tila 2 — sijoita käsin

Yksittäisten kuvien lisäämiseen tai korjaamiseen, kun automatiikka ei osu oikeaan:
anna tunnus ja kuvan polku vuorotellen, tyhjä tunnus lopettaa. Kuva menee seuraavaan
vapaaseen numeroon. Lisäys kirjataan kirjanpitoon, mutta duplikaatista vain
varoitetaan — käsin lisääminen on tietoinen valinta eikä sitä estetä.

### Tila 3 — luokitusten päivitys GeoPackageen

Palauttaa selaimessa tehdyt luokitukset alkuperäiseen GeoPackageen, jotta QGIS
näkee ne. Tila ei kysy kuvakansiota, hakuetäisyyksiä eikä GPX-tiedostoja.

| Kysymys | Selitys |
|---|---|
| **Kaavoittajan luokitus-GeoJSON** | Kartan **Lataa kaavoittajan suositukset** -napin tuottama tiedosto (`kaavoittajan_suositus_[projekti]_[pvm].geojson`, yleensä Lataukset-kansiossa). **Enter ohittaa** — silloin päivitetään vain viranomaisdata. |
| **Tallennus** | `1` = päälle, `2` = uudella nimellä (kopio, oletus `[nimi]_paivitetty.gpkg`). |
| **Viedäänkö myös kohteet.gpkg projektikansioon?** | Kopio `projektit/[projekti]/data/kohteet.gpkg`:hen. |
| **Viedäänkö kohteet.geojson ja pushataanko?** | Päivittää kartan näyttämään yhdistetyn datan. |

Viranomaisdata haetaan Sheetsistä automaattisesti, jos `config.json`:ssa on
`sheets_id`. Haku tehdään julkisena CSV:nä eikä vaadi kirjautumista.

**Päivitys tehdään paikan päällä SQLitellä**, ei tiedostoa uudelleen
kirjoittamalla. Samaan GeoPackageen tallennetut **QGIS-tyylit ja muut tasot
säilyvät** sekä päällekirjoituksessa että kopiossa. Puuttuvat sarakkeet
(`luokitus_vir`, `kommentti_vir`, `nimi_vir`, `virasto_vir`) lisätään tyhjinä.

Lopuksi tulostetaan montako riviä päivittyi kummastakin lähteestä ja mitkä
tunnukset eivät löytyneet GeoPackagesta:

```
  Päivitetty: /polku/ky_ita.gpkg
    Kaavoittajan luokituksia:   61
    Viranomaislausuntoja:       4
    ⚠ Tunnuksia ei löytynyt GeoPackagesta: 2  (EI_OLE_8888, EI_OLE_9999)
      Yleisin syy: väärä projekti tai vanhentunut GeoPackage.
```

### Ajon viestit

| Viesti | Mitä tehdä |
|---|---|
| `⚠ ei GPS EXIF:ssä` | Järjestelmäkameran kuva ilman geotägäystä — anna GPX-lokit, tai sijoita käsin (tila 2). |
| `✗ ei rakennusta N m säteellä` | Kuva otettu kaukaa tai GPS on epätarkka. Kasvata hakuetäisyyttä tai sijoita käsin. |
| `⚠ tunnus X jo 3 kuvaa` | Raja tulee vastaan. Poista jokin kuva käsin jos haluat korvata. |
| `↺ käsitelty jo aiemmin` | Normaali duplikaattisuoja, ei virhe. |
| `GPX-aukko N min — loggeri pois päältä?` | Kuva on otettu kun loggeri ei ollut päällä. Sijoita käsin tai anna puuttuva loki. |
| `aikaleima GPX-lokien ulkopuolella` | Kuvan aika ei osu mihinkään lokiin — puuttuuko loki, vai onko kameran kello pielessä (kellodrifti)? |
| `⚠ Tunnusta 'X' ei löydy GeoPackagesta` | Kuvat viittaavat rakennukseen jota ei ole aineistossa — tarkista että GeoPackage on ajan tasalla. |

---

## Osa B — Kartan katselu GitHubista

### Osoitteet

- `https://markushytonenpd.github.io/maasto/[projekti]/` — projektin oma sivu
- `https://markushytonenpd.github.io/maasto/?projekti=[nimi]` — vanha tapa, toimii yhä

Sivu hakee `config.json`:in (WMS-tasot) ja `data/kohteet.geojson`:in **Pages-kopiosta**,
jonka pipeline kopioi `docs/[projekti]/`:iin joka ajossa. Kuvien osoitteet ovat valmiiksi
geojsonissa. Uusi data näkyy heti pushin jälkeen, koska Pages tyhjentää välimuistinsa
julkaisun yhteydessä.

Jos Pages-kopio puuttuu (projekti kopioimatta), kartta hakee saman tiedoston
`raw.githubusercontent.com`ista polusta `projektit/[projekti]/`. Sitä kautta data voi olla
enintään 5 minuuttia vanhaa: raw tarjoilee tiedostot `max-age=300` -otsakkeella eikä sen
CDN revalidoi asiakkaan pyynnöstä — `?v=`-parametri tai `Cache-Control: no-cache` ei auta.
Oman selaimen välimuisti sen sijaan ohitetaan automaattisesti; jos silti epäilyttää,
päivitä kovalla latauksella (Ctrl+F5).

### Mitä sivulla voi tehdä

- **Pohjakartta:** Maastokartta (oletus) tai Taustakartta, oikean yläkulman valitsimesta.
- **Kaavatasot ym.:** projektin `config.json`:iin määritellyt WMS-tasot tulevat samaan
  valitsimeen.
- **Näkymävalitsin** vasemmassa yläkulmassa: *Kaavoittajan suositus* tai
  *Viranomaisen luokitus*. Valinta määrää sekä pisteiden värityksen että sen,
  kumpi osio popupissa on muokattavissa.
- **Kohteen popup:** kuvat (klikkaus suurentaa lightboxiin), valitut attribuutit
  taulukkona (`naytettavat_sarakkeet`), kaavoittajan suositus ja viranomaisen
  lausunto omina osioinaan.

#### Luokitusasteikko

Sama kolmiportainen asteikko molemmilla. Arvot tallentuvat GeoPackageen
merkkijonoina (`potentiaali`-sarake), joten QGIS-symboloinnit toimivat ennallaan.

| Väri | Selite kartalla | Arvo datassa |
|---|---|---|
| harmaa | Ei merkintää | tyhjä tai `ei arvoja` |
| sininen | Suositus säilyttämisestä | `paikallinen` |
| punainen | Suojelukohde | `suojelukohde` |

#### Kaavoittajan näkymä

Popupin *Kaavoittajan suositus* -osiossa on kolme painiketta. Valinta tallentuu
**vain selaimen localStorageen** (avain `luokitukset_kentta_[projekti]`) ja
pisteen väri muuttuu heti. Mitään ei lähetetä verkkoon.

Nappi **Lataa kaavoittajan suositukset** tuottaa tiedoston
`kaavoittajan_suositus_[projekti]_[pvm].geojson`, jossa muutokset ovat mukana.
Tämä tiedosto annetaan pipelinelle tilassa 3.

> **Muutokset ovat vain siinä selaimessa jossa ne on tehty.** Tyhjennä
> selaimen tiedot vasta kun olet ladannut tiedoston ja ajanut tilan 3.

#### Viranomaisen näkymä

Kun *Viranomaisen luokitus* on valittuna, popupin alaosa on lomake: luokitus,
kommentti, nimi ja virasto sekä **Tallenna**. Tallennus lähtee Apps Script
-endpointiin ja päätyy projektin Sheetiin — yksi rivi per rakennustunnus, eli
saman kohteen uusi lausunto päivittää vanhan.

- Nimi ja virasto muistetaan seuraavalle kohteelle.
- Kartta hakee Sheetin nykytilan käynnistyessään, joten toinen viranomainen
  näkee jo kirjatut lausunnot eikä ylikirjoita niitä vahingossa.
- Onnistumisesta tulee *Lausunto tallennettu ✓*, virheestä selkeä ilmoitus
  jossa lukee että lausuntoa **ei** tallennettu. Yritä silloin uudelleen.

Kaavoittajan näkymässä viranomaisen osio on vain luku.

> **Tallennus vaatii `apps_script_url`:n** projektin `config.json`:issa. Jos se
> puuttuu, Tallenna-nappi on pois käytöstä ja lomake kertoo syyn. Kartta, kuvat,
> attribuutit ja kaavoittajan luokittelu toimivat ilmankin. Endpointin
> deployaus: README kohta 4.

### Uusi projekti

Riittää että antaa pipelinelle uuden projektinimen — se luo `projektit/[nimi]/`-rakenteen,
`config.json`-pohjan ja `docs/[nimi]/index.html`:n, **luo viranomaislausuntojen Sheetin**
ja pushaa ne. Sheet luodaan vain kerran per projekti (pipeline tunnistaa sen
`sheets_id`-avaimesta).

Projektin `config.json` ensimmäisen ajon jälkeen:

```json
{
    "nimi": "Projektin nimi",
    "tasot": [
        { "nimi": "Kaavaluonnos",
          "url": "https://ubigu.ubihub.io/geoserver/kaavarasterit/ows",
          "layer": "kaavarasterit:layer_nimi",
          "nakyva": true }
    ],
    "naytettavat_sarakkeet": ["tunnus", "vuosi", "huom"],
    "sheets_id": "1AbC...",
    "sheets_valilehti": "Lausunnot",
    "apps_script_url": ""
}
```

| Avain | Mistä tulee |
|---|---|
| `tasot` | Lisätään käsin. |
| `naytettavat_sarakkeet` | Pipeline kysyy ajon alussa. |
| `sheets_id`, `sheets_valilehti` | Pipeline täyttää Sheetin luonnissa. |
| `apps_script_url` | **Täytetään käsin** Apps Script -deployauksen jälkeen (README kohta 4). Ilman tätä viranomainen ei voi tallentaa. |

Muista pushata `config.json` kun muokkaat sitä käsin — kartta lukee sen GitHubista.

---

## Vianetsintä

| Oire | Syy / korjaus |
|---|---|
| Sivu sanoo *Puuttuu URL-parametri* | Avattu juuri-URL ilman projektia. Käytä `/maasto/[projekti]/`. |
| Kartta tyhjä, ei kohteita | `kohteet.geojson` puuttuu tai pushaamatta. Aja pipeline loppuun ja tarkista `git log`. |
| Kuvat eivät näy popupissa | Kuvat pushaamatta, tai raw-välimuisti — odota muutama minuutti ja päivitä kovalla latauksella. |
| Uusi luokitus tai kaavataso ei näy heti | Puuttuuko `docs/[projekti]/config.json`? Ilman Pages-kopiota data tulee raw:sta 5 min viiveellä. Aja pipeline loppuun asti — se kopioi ja pushaa kopion. |
| Uusi kuva ei ilmesty | Onko rakennuksella jo 3 kuvaa, tai ohittiko kirjanpito kuvan duplikaattina? Katso ajon yhteenveto. |
| Kaavarasteri puuttuu, konsolissa CORS-virhe | GeoServeriin tarvitaan `Access-Control-Allow-Origin` — Ubigun ylläpito. Muu kartta toimii normaalisti. |
| Pohjakartta ei lataudu | MML-avain puuttuu tai vanhentunut `docs/config.js`:stä. |
| Popup näyttää väärät kentät | `naytettavat_sarakkeet` projektin `config.json`:issa. Aja pipeline ja valitse sarakkeet uudelleen, tai muokkaa käsin ja pushaa. |
| Viranomaisen Tallenna-nappi harmaana | `apps_script_url` puuttuu `config.json`:sta tai sitä ei ole pushattu. |
| *Tallennus epäonnistui: HTTP 401/403* | Apps Script -deployment ei ole tilassa *Käyttäjät: Kaikki*, tai URL on vanhan deploymentin. Tee uusi deployment ja päivitä URL. |
| Viranomaisen lausunnot eivät näy kartalla | Kartta hakee ne `apps_script_url`:sta. Tarkista selaimen konsolista *Lausuntojen haku Sheetsistä epäonnistui*. |
| Tila 3: *Sheetistä puuttuu sarakkeita* | Sheetin otsikkorivi on muuttunut. Palauta: `tunnus, luokitus_vir, kommentti_vir, nimi_vir, virasto_vir`. |
| Tila 3: *Tunnuksia ei löytynyt GeoPackagesta* | GeoJSON tai Sheet on eri projektista, tai GeoPackage on vanhentunut. |
| Pipeline varoittaa julkisesta muokkausoikeudesta | Drive-kansion linkkijako on *muokkaaja*. Vaihda kansion jaoksi **Rajoitettu** — muuten kuka tahansa Sheetin linkin saanut voi muokata lausuntoja. |
| *Google-kirjautumista ei ole tehty* | Aja `python3 auth_pipeline.py`. |

## Huomioitavaa

- **MML-avain on julkinen eikä sitä voi piilottaa.** `docs/config.js` on committoitu,
  koska Pages tarjoilee `docs/`-kansion suoraan repostosta; lisäksi selainsovelluksen
  avain paljastuu joka tapauksessa karttaruutupyynnöistä. MML:n avaimille ei voi
  asettaa verkkotunnus- tai viittaajarajausta, joten suojaus on: oma avain per
  julkaisu, ja väärinkäyttötilanteessa uusi avain OmaTilistä + vanhan poisto
  (ks. README, kohta 3).
- Rakennusta kohti mahtuu **3 kuvaa** — kartan popup lukee kentät `kuva1`–`kuva3`.
- GeoPackagea ei tallenneta repoon, joten pidä siitä huolta itse; pipeline lukee sen
  joka ajolla uudelleen ja rakentaa geojsonin sen pohjalta.
- **Viranomaislausuntojen Sheet on julkisesti luettava.** Se on tarkoituksellista:
  pipeline hakee datan ilman kirjautumista, eikä viranomainen tarvitse Google-tiliä.
  Älä siis kirjaa Sheetiin mitään mitä ei voi julkaista.
- **Drive-kansion jakoasetus periytyy Sheeteihin.** Jos kansio on jaettu linkillä
  muokkausoikeudella, jokainen sinne luotu Sheet on julkisesti muokattava eikä
  oikeutta voi laskea tiedostotasolla — Google estää sen. Pidä kansio
  *Rajoitettu*-tilassa; pipeline antaa lukuoikeuden erikseen jokaiselle Sheetille.
- **`credentials/`-kansio ei mene gitiin.** Siellä ovat OAuth-tunnistetiedot.

## Testit

```bash
python3 test_pipeline.py      # kuvien nimeäminen, GPX, duplikaattikirjanpito
python3 test_tila3.py         # GeoPackage-päivitys, QGIS-tyylien säilyminen
python3 test_kartta.py        # karttasovellus oikeassa selaimessa (Playwright)
python3 test_sheets_live.py --live   # Sheets-integraatio; LUO ja poistaa oikean Sheetin
```

Kolme ensimmäistä eivät koske verkkoon, projekteihin eivätkä gitiin. `test_kartta.py`
vaatii `pip install playwright && playwright install chromium` ja ohittuu siististi
jos sitä ei ole. Viimeinen vaatii `--live`-lipun eikä käynnisty vahingossa.
