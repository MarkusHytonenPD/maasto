# Käyttöohje — rakennusdokumentoinnin karttajulkaisu

Käytännön ohje päivittäiseen työhön. Ensiasennus (API-avaimet, Apps Script,
GitHub Pages, Python-riippuvuudet) on kuvattu erikseen [README.md](README.md):ssä.

---

## Kokonaiskuva: mikä ajetaan missä

Työnkulku on kaksiosainen.

```
  OMA KONE                              GITHUB
  ────────                              ──────
  kuvat + GPX-lokit                     repo MarkusHytonenPD/maasto
  GeoPackage (QGIS/QField)                  ├── projektit/[projekti]/kuvat/
          │                                 │   └── ky_[tunnus]_kuva1..3.jpg
          ▼                                 ├── projektit/[projekti]/data/
  python3 pipeline.py  ──── git push ──▶    │   └── kohteet.geojson
  (nimeää kuvat, tekee geojsonin,           └── docs/  → GitHub Pages
   commitoi ja pushaa itse)                          │
                                                     ▼
                                       https://markushytonenpd.github.io/maasto/[projekti]/
                                       (kuka tahansa selaimella, myös puhelimella)
```

**Pipeline ajetaan aina omalta koneelta.** Se tarvitsee paikalliset kuvat, GPX-lokit
ja GeoPackagen sekä paikallisen kloonin repostosta — mitään näistä ei ole GitHubissa.
Pipeline hoitaa julkaisun itse: se commitoi ja pushaa tulokset.

**Karttaa katsotaan GitHubista.** Selainsovellus on GitHub Pagesissa eikä katsoja
tarvitse mitään asennettua — pelkkä linkki riittää.

---

## Osa A — Pipelinen ajaminen omalta koneelta

### Tarvitset

- kuvakansion (puhelin, drone tai järjestelmäkamera)
- GPX-lokit, jos mukana on järjestelmäkameran kuvia joissa ei ole GPS:ää
- GeoPackagen jossa rakennukset ja `tunnus`-sarake (QGIS/QField-vienti)
- tämän repon paikallisena kloonina, push-oikeudet GitHubiin
- Python-riippuvuudet: `pip install geopandas pillow pyproj gpxpy piexif`

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
| **Tila** | `1` = pipeline (automaattinen), `2` = sijoita käsin. |
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

Sivu hakee datan suoraan raw.githubusercontent.com:sta main-haarasta:
`projektit/[projekti]/config.json` (WMS-tasot) ja `projektit/[projekti]/data/kohteet.geojson`.
Kuvien osoitteet ovat valmiiksi geojsonissa. Uusi data näkyy siis heti pushin jälkeen
ilman erillistä julkaisua — raw-palvelimen välimuisti voi viivästyttää muutaman
minuutin, ja selain kannattaa päivittää kovalla latauksella (Ctrl+F5).

### Mitä sivulla voi tehdä

- **Pohjakartta:** Maastokartta (oletus) tai Taustakartta, oikean yläkulman valitsimesta.
- **Kaavatasot ym.:** projektin `config.json`:iin määritellyt WMS-tasot tulevat samaan
  valitsimeen.
- **Teemapainikkeet** vasemmassa yläkulmassa: *Oma luokitus* (A+/A/B/C) tai
  *Viranomaisen luokitus* (Suojelukohde / Huomionarvoinen / Ei erityisiä arvoja).
  Viranomaisteema hakee luokitukset Google Sheetsistä.
- **Kohteen popup:** kuvat (klikkaus suurentaa lightboxiin), GeoPackagen attribuutit
  taulukkona, viranomaisen luokitus, kommentit ja lomake uuden kommentin lisäämiseen.
- **Kommentointi** tallentuu Google Sheetsiin Apps Script -endpointin kautta.

> **Kommentointi vaatii `SHEETS_URL`:n.** Se on tällä hetkellä tyhjä `docs/config.js`:ssä,
> joten kommentit ja viranomaisluokitukset eivät toimi ennen kuin Apps Script -endpoint
> on täytetty (README, kohta 4). Kartta, kuvat ja attribuutit toimivat ilmankin.

### Uusi projekti

Riittää että antaa pipelinelle uuden projektinimen — se luo `projektit/[nimi]/`-rakenteen,
`config.json`-pohjan ja `docs/[nimi]/index.html`:n sekä pushaa ne. WMS-tasot lisätään
käsin projektin `config.json`:iin:

```json
{
    "nimi": "Projektin nimi",
    "tasot": [
        { "nimi": "Kaavaluonnos",
          "url": "https://ubigu.ubihub.io/geoserver/kaavarasterit/ows",
          "layer": "kaavarasterit:layer_nimi",
          "nakyva": true }
    ]
}
```

---

## Vianetsintä

| Oire | Syy / korjaus |
|---|---|
| Sivu sanoo *Puuttuu URL-parametri* | Avattu juuri-URL ilman projektia. Käytä `/maasto/[projekti]/`. |
| Kartta tyhjä, ei kohteita | `kohteet.geojson` puuttuu tai pushaamatta. Aja pipeline loppuun ja tarkista `git log`. |
| Kuvat eivät näy popupissa | Kuvat pushaamatta, tai raw-välimuisti — odota muutama minuutti ja päivitä kovalla latauksella. |
| Uusi kuva ei ilmesty | Onko rakennuksella jo 3 kuvaa, tai ohittiko kirjanpito kuvan duplikaattina? Katso ajon yhteenveto. |
| Kaavarasteri puuttuu, konsolissa CORS-virhe | GeoServeriin tarvitaan `Access-Control-Allow-Origin` — Ubigun ylläpito. Muu kartta toimii normaalisti. |
| Pohjakartta ei lataudu | MML-avain puuttuu tai vanhentunut `docs/config.js`:stä. |
| Kommentit: *Sheets-haku epäonnistui* | `SHEETS_URL` on tyhjä tai Apps Script -julkaisu ei ole käytössä. |

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
