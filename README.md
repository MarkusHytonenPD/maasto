# maasto — Rakennusdokumentoinnin pipeline

Kenttäkuvista GitHub Pages -karttasivuksi. Käytössä QGIS, QField ja Python.

## Repon rakenne

```
maasto/
├── docs/                          ← GitHub Pages
│   ├── index.html                 ← karttasivu
│   ├── config.js                  ← EI commitoida (API-avaimet)
│   ├── config.example.js          ← pohja config.js:lle
│   └── apps_script.js             ← Google Apps Script -koodi
│
├── systeem/
│   ├── taustarasterit/
│   └── rajat/
│
├── projektit/
│   └── heinlansi/
│       ├── data/kohteet.geojson   ← pipeline.py tuottaa
│       └── kuvat/                 ← nimetyt kenttäkuvat
│
├── pipeline.py
├── .gitignore
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

1. Kirjaudu osoitteessa [maanmittauslaitos.fi](https://www.maanmittauslaitos.fi/rajapinnat/api-avaimet)
2. Luo uusi API-avain (tuote: Karttakuva, taustakartta, maastokartta)
3. Lisää avain `config.js`:n `MML_API_KEY`-kenttään

### 4. Google Apps Script — kommenttien tallennus

1. Luo tyhjä [Google Sheets](https://sheets.google.com) -taulukko
2. Avaa **Laajennukset → Apps Script**
3. Poista olemassa oleva koodi ja liitä `docs/apps_script.js`:n sisältö
4. Korvaa `SPREADSHEET_ID` taulukon ID:llä (löytyy URL:sta: `docs.google.com/spreadsheets/d/**[ID]**/edit`)
5. Tallenna ja julkaise: **Ota käyttöön → Web-app**
   - Suorita nimellä: **Minä**
   - Kuka voi käyttää: **Kaikki (myös anonyymit)**
6. Kopioi annettu endpoint-URL `config.js`:n `SHEETS_URL`-kenttään

Otsikkorivi luodaan taulukkoon automaattisesti ensimmäisellä kutsulla.

### 5. GitHub Pages

Repossa: **Settings → Pages → Source: Deploy from a branch**  
Branch: `main`, kansio: `/docs`

Sivusto julkaistuu osoitteessa `https://MarkusHytonenPD.github.io/maasto/`

### 6. Python-riippuvuudet

```bash
pip install geopandas pillow pyproj gpxpy piexif
pip install tzdata   # vain Windows
```

### 7. pipeline.py — kuvien käsittely ja julkaisu

Avaa `pipeline.py` ja aseta haluamasi projekti:

```python
PROJEKTI   = "heinlansi"       # vastaa projektit/-kansion nimeä
REPO_POLKU = Path(r"C:\GIS\maasto")
```

Aja skripti:

```bash
python pipeline.py
```

Skripti kysyy käynnistyessään kuvakansion, GeoPackagen ja layer-nimen sekä
mahdollisen GPX-tiedoston järjestelmäkameralle. Se nimeää kuvat, pushaa ne
GitHubiin ja tuottaa `projektit/[PROJEKTI]/data/kohteet.geojson` -tiedoston.

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

### Useampi projekti

Kopioi `projektit/heinlansi/`-rakenne uudelle projektille, vaihda `PROJEKTI`
pipeline.py:n alussa ja päivitä `config.js`:n `PROJEKTI`-kenttä.
