"use strict";

// ═══════════════════════════════════════════════════════════════
//  Karttasovellus rakennusinventoinnin luokitukseen.
//
//  Kaavoittaja ja kolme viranomaistahoa luokittelevat samat kohteet
//  samalla asteikolla, kukin omana tahonaan. Kaikki kirjaukset menevät
//  samaan Google Sheetiin avaimella (tunnus, taho), joten kukaan ei
//  ylikirjoita toisen työtä ja kartta näyttää tuoreimman tilan.
//
//  Kaavoittajan lähtöarvo on Vastuumuseon kanta: museon luokitus
//  sellaisenaan, museon kommentoima mutta luokittelematon kohde
//  "tarvitaan lisätietoja", ja kokonaan ilman huomioita jäänyt kohde
//  "ei suojeluarvoja / säilymisen edellytyksiä".
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════
//  CRS — ETRS-TM35FIN (EPSG:3067)
// ═══════════════════════════════════════════════════════════════

const crs = new L.Proj.CRS(
  "EPSG:3067",
  "+proj=utm +zone=35 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs",
  {
    resolutions: [8192, 4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25],
    origin: [-548576, 8388608],
    bounds: L.bounds([-548576, 6291456], [1548576, 8388608]),
  }
);

// ═══════════════════════════════════════════════════════════════
//  KARTTA
// ═══════════════════════════════════════════════════════════════

const map = L.map("map", { crs, center: [62.4, 28.5], zoom: 9 });

const MML_URL_POHJA =
  "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0/{layer}/default/ETRS-TM35FIN/{z}/{y}/{x}.png?api-key={apikey}";

const mmlMaasto = L.tileLayer(MML_URL_POHJA, {
  layer: "maastokartta", apikey: CONFIG.MML_API_KEY,
  opacity: 0.3, attribution: "&copy; MML",
});
mmlMaasto.addTo(map);

const mmlTausta = L.tileLayer(MML_URL_POHJA, {
  layer: "taustakartta", apikey: CONFIG.MML_API_KEY,
  opacity: 1.0, attribution: "&copy; MML",
});

// Taustakartat ovat rasteja, eivät radionappeja: Leafletin pohjakartta-
// valinnassa yksi on aina päällä, eikä maakuntakaavaa voisi katsoa
// puhtaalta pohjalta. Molemmat voi nyt sammuttaa.
const layerControl = L.control.layers({}, {}, { collapsed: false }).addTo(map);
layerControl.addOverlay(mmlMaasto, "Maastokartta");
layerControl.addOverlay(mmlTausta, "Taustakartta");

// ═══════════════════════════════════════════════════════════════
//  LUOKITUSMALLI
//  Kuusiportainen asteikko, sama kaavoittajalle ja viranomaisille.
//  arvo = se merkkijono joka on GeoPackagessa ja Sheetsissä.
//
//  HUOM arvoista: "ei_suojeluarvoja" on alaviivalla, koska aineistossa
//  esiintyvä "ei arvoja" tarkoittaa tyhjää (ks. TYHJAT) — samannäköinen
//  arvo luettaisiin luokaksi "Ei merkintää".
// ═══════════════════════════════════════════════════════════════

// Järjestys kulkee suojeluarvon mukaan; "tarvitaan lisätietoja" on
// viimeisenä, koska se on keskeneräisyyden merkintä eikä asteikon askel.
//
// Symboliikka kantaa kaksi tietoa erikseen:
//   vari  — suojeluarvo. Kaikki suojelukohteet ovat punaisia riippumatta
//           siitä kumoutuvatko ne.
//   katko — kumoutuminen. Kumoutuvan alueen luokat piirtyvät katkoviivalla,
//           muut yhtenäisellä.
// Kolmiportainen viivanpaksuus (paksuusero lisätään perusviivaan):
//   MK-suojelukohde  +1,5  pitkä katko, paksuin viiva
//   yhtenäiset         0
//   muut katkoviivat  -1   ohuin viiva
// Näin kaksi punaista kumoutuvaa luokkaa erottuu sekä katkon tiheydellä
// että paksuudella, ja katkoviiva kevenee kartalla.
//   muoto — "rengas" (oletus), "piste" tai "kysymys"
const LUOKAT = [
  { arvo: "ei_suojeluarvoja",          selite: "Ei suojeluarvoja / säilymisen edellytyksiä",
    vari: "#000000", muoto: "piste" },
  { arvo: "kumottava",                 selite: "Kumottavalla alueella",     vari: "#7570b3",
    katko: "6 5", paksuusero: -1 },
  { arvo: "kumoutuva_mk_suojelukohde", selite: "Kumoutuva MK-suojelukohde", vari: "#e31a1c",
    katko: "12 6", paksuusero: 1.5 },
  { arvo: "kumoutuva_suojelukohde",    selite: "Kumoutuva suojelukohde",    vari: "#e31a1c",
    katko: "4 4", paksuusero: -1 },
  { arvo: "paikallinen",               selite: "Suositus säilyttämisestä",  vari: "#1f78b4" },
  { arvo: "suojelukohde",              selite: "Suojelukohde",              vari: "#e31a1c" },
  { arvo: "lisatietoja",               selite: "Tarvitaan lisätietoja",     vari: "#e31a1c",
    muoto: "kysymys" },
];

// Tyhjä arvo ei ole enää valittava luokka: kaavoittajalla jokaisella
// kohteella on Vastuumuseon pohja-arvo, ja viranomaisella tyhjä tarkoittaa
// "ei ole vielä kommentoinut". Harmaa on tummempi kuin popupin harmaat
// tekstit: ääriviivana vaalea harmaa hukkui maastokartan viivastoon.
const EI_KIRJAUSTA = { arvo: "", selite: "Ei kommenttia", vari: "#555555" };

// Vastuumuseon kannan puuttuessa käytettävät lähtöluokat
const EI_SUOJELUARVOJA = "ei_suojeluarvoja";
const LISATIETOJA      = "lisatietoja";

// Aineistossa esiintyvä "ei arvoja" tarkoittaa samaa kuin tyhjä.
const TYHJAT = ["", "ei arvoja", "0", "null", "none", "nan"];

const TUNNUS         = "tunnus";
const LUOKITUS       = "potentiaali";      // kaavoittajan luokitus GeoPackagessa
const KUVAT          = ["kuva1", "kuva2", "kuva3"];

// Sheetin ja endpointin kenttänimet. Sheetissä on yksi rivi per (tunnus, taho).
const TAHO           = "taho";
const LUOKITUS_VIR   = "luokitus_vir";
const KOMMENTTI_VIR  = "kommentti_vir";
const NIMI_VIR       = "nimi_vir";

// Kaavoittaja tallentaa samaan Sheetiin omana tahonaan.
//
// vanhatNimet: kehitysvaiheessa rivit kirjattiin taholla "Kaavoittaja (demo)".
// Ne luetaan yhä, jotta Sheetin rivien uudelleennimeäminen ei ole kiireellistä
// eikä kartta näytä välillä tyhjää. Kirjoitus käyttää aina nykyistä nimeä, ja
// jos kohteella on molemmat rivit, nykyinen voittaa.
const KAAVOITTAJA = {
  avain: "kaav",
  nimi: "Kaavoittaja",
  vanhatNimet: ["Kaavoittaja (demo)"],
};

// Kolme kommentoijatahoa, kukin tallentaa ja näkyy kartalla erikseen.
//   avain = GeoJSONin sarakepääte, nimi = Sheetin taho-arvo ja käyttöliittymä
const TAHOT = [
  { avain: "lvv",    nimi: "LVV" },
  { avain: "museo",  nimi: "Vastuumuseo" },
  { avain: "liitto", nimi: "Maakuntaliitto" },
];

// Kaikki Sheetiin kirjaavat: kaavoittaja + viranomaistahot
const TALLENTAJAT = [KAAVOITTAJA, ...TAHOT];

const MUSEO = "museo";

/** GeoJSONin tahokohtainen sarake: ("luokitus", "lvv") → "luokitus_lvv". */
function virSarake(kentta, avain) {
  return `${kentta}_${avain}`;
}

// Kaikki tahokohtaiset sarakkeet — nämä esitetään omissa osioissaan, ei
// attribuuttitaulussa
const VIR_SARAKKEET = TALLENTAJAT.flatMap(taho =>
  ["luokitus", "kommentti", "nimi"].map(kentta => virSarake(kentta, taho.avain)));

// Sarakkeiden näyttöotsikot. Muut sarakkeet näytetään omalla nimellään.
const OTSIKOT = {
  [LUOKITUS]:      "Kaavoittajan luokitus",
  [LUOKITUS_VIR]:  "Luokitus",
  [KOMMENTTI_VIR]: "Kommentti",
  [NIMI_VIR]:      "Nimi",
};

function normalisoiLuokka(arvo) {
  const teksti = String(arvo === null || arvo === undefined ? "" : arvo).trim().toLowerCase();
  return TYHJAT.includes(teksti) ? "" : teksti;
}

function luokka(arvo) {
  const normi = normalisoiLuokka(arvo);
  return LUOKAT.find(l => l.arvo === normi) || null;
}

/** Tuntematon arvo näytetään sellaisenaan, väri harmaa. */
function luokkaSelite(arvo) {
  const l = luokka(arvo);
  if (l) return l.selite;
  return String(arvo);
}

function luokkaVari(arvo) {
  const l = luokka(arvo);
  return l ? l.vari : EI_KIRJAUSTA.vari;
}

// ═══════════════════════════════════════════════════════════════
//  TILA
// ═══════════════════════════════════════════════════════════════

let PROJEKTI        = "";
let projektiConfig  = {};
let geojsonData     = null;
let geojsonLayer    = null;
// Kioski 3.0 -kohdetiedot tunnuksittain (data/kioski.json, kioski_tuonti.py).
// Valinnainen: jos tiedostoa ei ole, osio jää pois popupista.
let kioskiData      = {};
// KAAVOITTAJA.avain ("kaav") tai tahon avain ("lvv" | "museo" | "liitto")
let aktiivinen_nakyma = KAAVOITTAJA.avain;
const markkerit     = {};                  // tunnus → layer

// Sheetsistä haetut kirjaukset: { "tunnus|tahoavain": {luokitus_vir, ...} }
// Nämä ovat tuoreempia kuin GeoJSONin arvot, jotka päivittyvät vain
// pipeline-ajossa. Avaimessa on taho, koska useampi taho lausuu samasta
// kohteesta toisistaan riippumatta.
let sheetsKommentit = {};

// Kohteet piirretään heti GeoJSONin arvoilla, ja Sheetin kirjaukset tulevat
// perässä (Apps Script vastaa kylmänä jopa puolessa minuutissa). Haun ajan
// lomakkeet ja lataus ovat lukossa, jottei vanhentuneella esitäytöllä
// tallennettu kirjaus korvaa Sheetin tuoreempaa riviä.
let kirjauksetHaussa = false;
const KIRJAUSTEN_AIKARAJA_MS = 60000;

/** Avain sheetsKommentit-hakuun. */
function kommenttiAvain(tunnus, tahoAvain) {
  return `${tunnus}|${tahoAvain}`;
}

const VIR_TIEDOT_AVAIN = "viranomainen_tiedot";   // oma nimi muistiin

/**
 * Yhden tallentajan arvot: Sheetsin tuore rivi voittaa GeoJSONin sarakkeet.
 * Palauttaa null jos kirjausta ei ole kummassakaan — kutsuja päättää mitä
 * tyhjä tarkoittaa (viranomaisella "ei kommenttia", kaavoittajalla museon
 * pohja-arvo).
 */
function tallentajaKirjaus(props, tahoAvain) {
  const tunnus = String(props[TUNNUS] ?? "");
  const rivi   = sheetsKommentit[kommenttiAvain(tunnus, tahoAvain)];
  if (rivi) return rivi;

  const geo = {
    [LUOKITUS_VIR]:  props[virSarake("luokitus", tahoAvain)],
    [KOMMENTTI_VIR]: props[virSarake("kommentti", tahoAvain)],
    [NIMI_VIR]:      props[virSarake("nimi", tahoAvain)],
  };
  const onSisaltoa = [LUOKITUS_VIR, KOMMENTTI_VIR, NIMI_VIR].some(k => !tyhja(geo[k]));
  return onSisaltoa ? geo : null;
}

/** Viranomaisen arvot — puuttuva kirjaus näkyy tyhjänä. */
function viranomaisArvot(props, tahoAvain) {
  return tallentajaKirjaus(props, tahoAvain) || {
    [LUOKITUS_VIR]: "", [KOMMENTTI_VIR]: "", [NIMI_VIR]: "",
  };
}

/**
 * Vastuumuseon kanta on jokaisen kohteen lähtöarvo.
 *
 * Luokittelematon kohde ei tarkoita aina samaa: museo on jättänyt osan
 * kokonaan ilman huomioita, mutta osaan se on kirjoittanut kommentin
 * luokittelematta ("Arvot?", "Ei voi näillä tiedoilla arvioida."). Nämä ovat
 * kysymyksiä, joten niiden pohja on "tarvitaan lisätietoja" — muuten museon
 * esittämä kysymys katoaisi pohja-arvon "ei suojeluarvoja" alle.
 */
function museoPohja(props) {
  const arvot    = viranomaisArvot(props, MUSEO);
  const luokitus = normalisoiLuokka(arvot[LUOKITUS_VIR]);
  if (luokitus) return luokitus;
  return tyhja(arvot[KOMMENTTI_VIR]) ? EI_SUOJELUARVOJA : LISATIETOJA;
}

/**
 * Kaavoittajan kanta kohteeseen.
 *   oma = true  → kaavoittaja on itse kirjannut arvon (Sheet)
 *   oma = false → arvo on vielä Vastuumuseon pohja, kantaa ei ole otettu
 *
 * GeoPackagen vanhaa potentiaali-saraketta ei lueta: tämän kierroksen pohja
 * otetaan museolta, ja vanhat kenttäluokitukset korvautuvat vasta kun
 * kaavoittaja on käynyt kohteen läpi.
 */
function kaavoittajaKanta(props) {
  const kirjaus = tallentajaKirjaus(props, KAAVOITTAJA.avain);
  if (kirjaus) return { arvot: kirjaus, oma: true };
  return {
    arvot: { [LUOKITUS_VIR]: museoPohja(props), [KOMMENTTI_VIR]: "", [NIMI_VIR]: "" },
    oma:   false,
  };
}

/** Aktiivisen näkymän arvot yhdellä kutsulla. */
function nykyinenKanta(props) {
  if (aktiivinen_nakyma === KAAVOITTAJA.avain) return kaavoittajaKanta(props);
  return { arvot: viranomaisArvot(props, aktiivinen_nakyma), oma: true };
}

function appsScriptUrl() {
  const url = projektiConfig.apps_script_url;
  return tyhja(url) ? "" : String(url).trim();
}

/**
 * Lausuntokierros päättynyt: kirjaukset luetaan jäädytetystä
 * data/kirjaukset.json:ista (jaadyta_kirjaukset.py) eikä mitään voi tallentaa.
 */
function kirjauksetLukittu() {
  return projektiConfig.kirjaukset_lukittu === true;
}

// Jäädytyksen ajankohta (kirjaukset.json:in "haettu"), näytetään lomakkeessa
let kirjauksetHaettu = "";

/**
 * Hakee Sheetin nykytilan Apps Scriptin doGet-rajapinnasta, tai lukitussa
 * projektissa jäädytetyn tilan samassa muodossa.
 */
async function haeKommentit() {
  const url = appsScriptUrl();
  if (!url && !kirjauksetLukittu()) return;
  try {
    let data;
    if (kirjauksetLukittu()) {
      data = await haeData("data/kirjaukset.json");
      kirjauksetHaettu = data.haettu || "";
    } else {
      // Aikaraja: jumiin jäänyt haku pitäisi lomakkeet lukossa loputtomiin
      const resp = await fetch(url, { signal: AbortSignal.timeout(KIRJAUSTEN_AIKARAJA_MS) });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
    }
    if (data.status !== "ok" || !Array.isArray(data.rivit)) {
      throw new Error(data.message || "odottamaton vastaus");
    }
    sheetsKommentit = {};
    let tuntemattomia = 0;

    const tahoNimesta = nimi =>
      TALLENTAJAT.find(x => x.nimi === nimi) || null;
    const tahoVanhastaNimesta = nimi =>
      TALLENTAJAT.find(x => (x.vanhatNimet || []).includes(nimi)) || null;

    // Vanhalla nimellä kirjatut ensin, nykyiset päälle: jos kohteella on
    // molemmat rivit, nykyinen voittaa.
    const rivit = [...data.rivit].sort((a, b) => {
      const va = tahoNimesta(String(a[TAHO] ?? "").trim()) ? 1 : 0;
      const vb = tahoNimesta(String(b[TAHO] ?? "").trim()) ? 1 : 0;
      return va - vb;
    });

    rivit.forEach(r => {
      const tunnus = String(r.tunnus ?? "").trim();
      const nimi   = String(r[TAHO] ?? "").trim();
      const taho   = tahoNimesta(nimi) || tahoVanhastaNimesta(nimi);
      if (!tunnus) return;
      // Tuntematon taho jätetään pois: muuten kirjaus ei näkyisi missään
      // näkymässä mutta olisi silti Sheetissä
      if (!taho) { tuntemattomia++; return; }
      sheetsKommentit[kommenttiAvain(tunnus, taho.avain)] = r;
    });
    if (tuntemattomia) {
      console.warn(`Sheetissä ${tuntemattomia} riviä tuntemattomalla taholla`);
    }
    console.log(`Kirjauksia Sheetsistä: ${Object.keys(sheetsKommentit).length}`);
  } catch (e) {
    // Kartta toimii ilman tätäkin — GeoJSONin arvot ovat silloin käytössä
    console.warn("Kirjausten haku Sheetsistä epäonnistui:", e);
  }
}

/**
 * Muistaa kirjaajan oman nimen, jottei sitä kirjoiteta uudelleen.
 * Nimeä EI esitäytetä Sheetistä: silloin toisen tahon kirjaaman nimen voisi
 * tallentaa vahingossa omaksi.
 */
function lueVirTiedot() {
  try {
    const tiedot = JSON.parse(localStorage.getItem(VIR_TIEDOT_AVAIN) || "{}");
    return { nimi: tiedot.nimi || "" };
  } catch (e) {
    return { nimi: "" };
  }
}

function tallennaVirTiedot(nimi) {
  try {
    localStorage.setItem(VIR_TIEDOT_AVAIN, JSON.stringify({ nimi }));
  } catch (e) {
    console.warn("localStorage-tallennus epäonnistui:", e);
  }
}

// ═══════════════════════════════════════════════════════════════
//  APUFUNKTIOT
// ═══════════════════════════════════════════════════════════════

const ESC_MERKIT = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function esc(arvo) {
  return String(arvo === null || arvo === undefined ? "" : arvo)
    .replace(/[&<>"']/g, m => ESC_MERKIT[m]);
}

function tyhja(arvo) {
  return arvo === null || arvo === undefined || String(arvo).trim() === "";
}

/** 1800.0 → "1800", muu arvo sellaisenaan. */
function muotoile(arvo) {
  if (typeof arvo === "number" && Number.isFinite(arvo) && Number.isInteger(arvo)) {
    return String(arvo);
  }
  return String(arvo);
}

function otsikko(sarake) {
  return OTSIKOT[sarake] || sarake;
}

/**
 * Popupissa näytettävät attribuuttisarakkeet config.json:sta.
 *
 * Luokitus- ja viranomaissarakkeilla on popupissa omat osionsa, joten ne
 * jätetään attribuuttitaulusta pois myös silloin kun ne on valittu
 * naytettavat_sarakkeet-listaan — muuten sama arvo näkyisi kahdesti, ja
 * ylempi esiintymä olisi se jota ei voi muokata.
 */
function naytettavatSarakkeet(props) {
  const piilota = new Set([LUOKITUS, ...VIR_SARAKKEET, ...KUVAT]);
  const valitut = projektiConfig.naytettavat_sarakkeet;
  if (Array.isArray(valitut) && valitut.length) {
    return valitut.filter(s => s in props && !piilota.has(s));
  }
  return Object.keys(props).filter(s => !piilota.has(s));
}

// ═══════════════════════════════════════════════════════════════
//  DATAN HAKU
//  Ensisijainen lähde on GitHub Pages, jonne pipeline kopioi
//  config.json:in ja kohteet.geojsonin: Pages tyhjentää CDN-
//  välimuistinsa deployn yhteydessä, joten pipeline-ajon tulokset
//  näkyvät kartalla heti. raw.githubusercontent.com on varalla
//  projekteille joita ei ole kopioitu docs/:iin — se tarjoilee
//  tiedostot max-age=300 -otsakkeella eikä revalidoi pyynnöstä,
//  joten sen kautta data voi olla viisi minuuttia vanhaa.
// ═══════════════════════════════════════════════════════════════

/** Projektin tiedoston polku nykyisestä sivusta katsottuna. */
function pagesPolku(tiedosto) {
  const kansiot = new URL(".", document.baseURI).pathname.split("/").filter(Boolean);
  // docs/[projekti]/index.html → tiedosto on samassa kansiossa.
  // docs/index.html?projekti=… → projektin kansion kautta.
  return kansiot[kansiot.length - 1] === PROJEKTI
    ? tiedosto
    : `${encodeURIComponent(PROJEKTI)}/${tiedosto}`;
}

async function haeData(tiedosto) {
  const busteri = `v=${Date.now()}`;    // ohittaa selaimen oman välimuistin
  const lahteet = [];
  // file://-sivulla suhteellinen fetch ei ole sallittu — silloin vain raw
  if (location.protocol.startsWith("http")) {
    lahteet.push(`${pagesPolku(tiedosto)}?${busteri}`);
  }
  lahteet.push(`${CONFIG.GITHUB_RAW}/projektit/${PROJEKTI}/${tiedosto}?${busteri}`);

  let virhe = new Error("ei lähteitä");
  for (const url of lahteet) {
    try {
      const vastaus = await fetch(url, { cache: "no-store" });
      if (vastaus.ok) return await vastaus.json();
      virhe = new Error(`HTTP ${vastaus.status} — ${url}`);
    } catch (e) {
      virhe = e;
    }
  }
  throw virhe;
}

// ═══════════════════════════════════════════════════════════════
//  TEEMOITUS
// ═══════════════════════════════════════════════════════════════

const MARKKERI_SADE = 14;

const PISTE_SADE = 3.5;

// Kaavoittajan käymättä oleva kohde piirtyy ohuella viivalla, oma kirjaus
// paksulla. Katkoviiva ei ole käytettävissä tähän (se merkitsee
// kumoutumista), eikä haalennus: 45 %:n peitolla symboli hukkui
// maastokartan viivastoon ja kaavarasteriin.
const POHJAN_VIIVA = 2;
const OMAN_VIIVA   = 4;

// Ikonin laatikko. Renkaan halkaisija on 28 px, joten reunoille jää tilaa
// paksuimmalle viivalle ja valkoiselle hehkulle.
const IKONI_KOKO = 36;

/**
 * Symbolin määrittely luokasta ja kirjauksen tilasta. Erillään piirrosta,
 * jotta sama määrittely kelpaa sekä kartalle että selitteeseen.
 *
 * muoto  — luokan symboli: rengas, piste tai kysymysmerkki
 * vari   — suojeluarvo
 * katko  — kumoutuminen
 * viiva  — ohut = vielä Vastuumuseon pohja, paksu = kaavoittajan oma kanta
 * tayttö — pisteellä ja kysymysmerkillä sama ero näkyy täyttönä: ääriviiva
 *          yksin = pohja-arvo, täytetty = oma kirjaus
 */
function symboliSpec(props) {
  const { arvot, oma } = nykyinenKanta(props);
  const lk    = luokka(arvot[LUOKITUS_VIR]);
  const muoto = lk && lk.muoto ? lk.muoto : "rengas";
  return {
    muoto,
    vari:   lk ? lk.vari : EI_KIRJAUSTA.vari,
    viiva:  (oma ? OMAN_VIIVA : POHJAN_VIIVA) + (lk && lk.paksuusero ? lk.paksuusero : 0),
    katko:  lk && lk.katko ? lk.katko : "",
    tayttö: muoto !== "rengas" && oma,
  };
}

/**
 * Symboli SVG:nä. Katkoviiva skaalataan säteestä, joten selitteen pienempi
 * merkki näyttää samalta kuvioilta kuin karttasymboli.
 *
 * Rengas on täyttämätön, jotta kaavarasteri näkyy symbolin läpi.
 */
function symboliSvg(spec, koko, sade) {
  const c = koko / 2;
  const avaa = `<svg width="${koko}" height="${koko}" viewBox="0 0 ${koko} ${koko}" aria-hidden="true">`;

  if (spec.muoto === "kysymys") {
    const yhteinen = `x="${c}" y="${c}" text-anchor="middle" dominant-baseline="central" ` +
      `font-family="sans-serif" font-weight="700" font-size="${(sade * 2.3).toFixed(1)}"`;
    const tyyli = spec.tayttö
      ? `fill="${spec.vari}"`
      : `fill="none" stroke="${spec.vari}" stroke-width="1.3"`;
    return `${avaa}<text ${yhteinen} ${tyyli}>?</text></svg>`;
  }

  if (spec.muoto === "piste") {
    // Selitteessä alaraja: suhteessa skaalattu piste kutistuisi
    // näkymättömäksi, ja selite on muutenkin kaavakuva eikä mittakaavassa.
    const r = Math.max(2.5, PISTE_SADE * (sade / MARKKERI_SADE));
    return `${avaa}<circle cx="${c}" cy="${c}" r="${r.toFixed(1)}" ` +
      `fill="${spec.tayttö ? spec.vari : "none"}" ` +
      `stroke="${spec.vari}" stroke-width="2" /></svg>`;
  }

  const suhde = sade / MARKKERI_SADE;
  const kuvio = spec.katko
    ? ` stroke-dasharray="${spec.katko.split(" ")
        .map(x => (Number(x) * suhde).toFixed(1)).join(" ")}"`
    : "";
  return `${avaa}<circle cx="${c}" cy="${c}" r="${sade}" fill="none" ` +
    `stroke="${spec.vari}" stroke-width="${spec.viiva}"${kuvio} /></svg>`;
}

/**
 * Symbolit ovat divIcon-markkereita, eivät circleMarkereita: kysymysmerkki
 * ei ole ympyrä. Ikonin vaihto onnistuu paikan päällä setIcon():lla, joten
 * luokan symbolin muuttuminen tallennuksessa ei sulje popupia.
 */
function luoIkoni(props) {
  return L.divIcon({
    html:       symboliSvg(symboliSpec(props), IKONI_KOKO, MARKKERI_SADE),
    className:  "kohde-symboli",
    iconSize:   [IKONI_KOKO, IKONI_KOKO],
    iconAnchor: [IKONI_KOKO / 2, IKONI_KOKO / 2],
  });
}

function luoMarker(feature, latlng) {
  return L.marker(latlng, { icon: luoIkoni(feature.properties), keyboard: false });
}

/**
 * Tunnus näkyviin pisteen viereen, jotta kohde on tunnistettavissa
 * kartalta ilman popupin avaamista (esim. luetteloa vasten luettaessa).
 */
function lisaaTunnusOtsikko(layer, tunnus) {
  if (!tunnus) return;
  layer.bindTooltip(esc(tunnus), {
    permanent: true,
    direction: "right",
    // Symbolin reunan ulkopuolelle, muuten otsikko osuisi ympyrän päälle
    offset:    [MARKKERI_SADE + 5, 0],
    opacity:   1,
    className: "tunnus-otsikko",
  });
}

function paivitaLayer() {
  if (!geojsonData) return;
  if (geojsonLayer) map.removeLayer(geojsonLayer);
  geojsonLayer = L.geoJSON(geojsonData, {
    pointToLayer: luoMarker,
    onEachFeature(feature, layer) {
      const tunnus = String(feature.properties[TUNNUS] ?? "");
      markkerit[tunnus] = layer;
      lisaaTunnusOtsikko(layer, tunnus);
      layer.bindPopup(() => luoPopup(feature, layer), {
        maxWidth:  440,
        maxHeight: 640,
        // Kartta panoroidaan niin ettei popup jää kontrollien alle:
        // vasemmalla näkymävalitsin (~200 px), oikealla tasovalitsin.
        // Z-indeksillä tätä ei voi ratkaista — ks. kartta.css.
        autoPanPaddingTopLeft:     [230, 20],
        autoPanPaddingBottomRight: [210, 20],
      });
    },
  }).addTo(map);
  paivitaSelitys();
}

/**
 * Sheetin kirjausten saavuttua: kaikki symbolit ja selite päivitetään
 * paikan päällä, ja auki oleva popup piirretään uudelleen tuoreilla
 * arvoilla. Lomake on ollut haun ajan lukossa, joten mitään syötettyä
 * ei katoa.
 */
function kirjauksetSaapuivat() {
  kirjauksetHaussa = false;
  const nappi = document.getElementById("lataa-suositukset");
  if (nappi) nappi.disabled = false;
  if (!geojsonData) return;
  geojsonData.features.forEach(f => {
    const layer = markkerit[String(f.properties[TUNNUS] ?? "")];
    if (layer && layer.setIcon) layer.setIcon(luoIkoni(f.properties));
  });
  paivitaSelitys();
  const avoin = Object.values(markkerit).find(l => l.isPopupOpen());
  if (avoin) avoin.getPopup().update();
}

/** Päivittää yhden symbolin ilman että popup sulkeutuu. */
function paivitaMarkkeri(tunnus, props) {
  const layer = markkerit[String(tunnus)];
  if (layer && layer.setIcon) layer.setIcon(luoIkoni(props));
  paivitaSelitys();
}

// ═══════════════════════════════════════════════════════════════
//  POPUP
// ═══════════════════════════════════════════════════════════════

function popupOtsikko(props, tunnus) {
  const nimi = !tyhja(props.nimi) ? props.nimi : (!tyhja(props.name) ? props.name : tunnus);
  const el = document.createElement("div");
  el.className = "pu-otsikko";
  // Ilman nimeä otsikkona on tunnus — ei toisteta sitä suluissa
  el.innerHTML = String(nimi) === tunnus
    ? esc(nimi)
    : `${esc(nimi)} <span class="pu-tunnus">(${esc(tunnus)})</span>`;
  return el;
}

function popupKuvat(props) {
  const urlit = KUVAT.map(k => props[k]).filter(u => !tyhja(u));
  if (!urlit.length) return null;
  const el = document.createElement("div");
  el.className = "pu-kuvat";
  urlit.forEach(url => {
    const img = document.createElement("img");
    img.src = url;
    img.alt = "kuva";
    img.addEventListener("click", () => avaaLightbox(url));
    el.appendChild(img);
  });
  return el;
}

function popupAttribuutit(props) {
  const rivit = naytettavatSarakkeet(props)
    .filter(s => !tyhja(props[s]))
    .map(s => `<tr><td>${esc(otsikko(s))}</td><td>${esc(muotoile(props[s]))}</td></tr>`);
  if (!rivit.length) return null;
  const el = document.createElement("div");
  el.className = "pu-attr";
  el.innerHTML = `<table>${rivit.join("")}</table>`;
  return el;
}

function osio(otsikkoteksti, luokkaNimi) {
  const el = document.createElement("div");
  el.className = luokkaNimi;
  const h = document.createElement("h4");
  h.textContent = otsikkoteksti;
  el.appendChild(h);
  return el;
}

/**
 * Viranomaistahojen kirjaukset vain luettavina. Näytetään aina, myös silloin
 * kun yhtä tahoa muokataan: kirjaajan on nähtävä muiden kannat.
 */
function popupViranomaisetLuku(props, korostettuTaho) {
  const el = osio("Viranomaisten kommentit", "pu-vir");

  const rivit = TAHOT.map(taho => {
    const arvot = viranomaisArvot(props, taho.avain);
    const lk    = luokka(arvot[LUOKITUS_VIR]);
    const on    = !tyhja(arvot[LUOKITUS_VIR]) || !tyhja(arvot[KOMMENTTI_VIR]);
    const lisat = [arvot[KOMMENTTI_VIR], arvot[NIMI_VIR]]
      .filter(x => !tyhja(x)).map(x => esc(x)).join(" — ");
    const korostus = taho.avain === korostettuTaho ? " pu-taho-aktiivinen" : "";
    return `<tr class="pu-taho${korostus}">
        <td><span class="pu-taho-merkki" style="background:${lk ? lk.vari : EI_KIRJAUSTA.vari}"></span>${esc(taho.nimi)}</td>
        <td>${on ? esc(luokkaSelite(arvot[LUOKITUS_VIR])) : '<span class="pu-vir-tyhja">Ei kommenttia</span>'}
            ${lisat ? `<div class="pu-taho-lisa">${lisat}</div>` : ""}</td>
      </tr>`;
  });

  const taulu = document.createElement("div");
  taulu.className = "pu-attr";
  taulu.innerHTML = `<table>${rivit.join("")}</table>`;
  el.appendChild(taulu);
  return el;
}

/** Kaavoittajan kanta muiden näkymien popupissa, yhdellä rivillä. */
function popupKaavoittajaLuku(props) {
  const { arvot, oma } = kaavoittajaKanta(props);
  const el = document.createElement("div");
  el.className = "pu-kaava pu-kaava-luku";

  const otsake = document.createElement("span");
  otsake.className = "pu-kaava-otsake";
  otsake.textContent = "Kaavoittajan luokitus:";

  const arvo = document.createElement("span");
  arvo.className = "pu-lukuarvo";
  arvo.textContent = luokkaSelite(arvot[LUOKITUS_VIR]);

  el.appendChild(otsake);
  el.appendChild(arvo);
  if (!oma) {
    const merkki = document.createElement("span");
    merkki.className = "pu-pohja";
    merkki.textContent = "museon pohja";
    el.appendChild(merkki);
  }
  return el;
}

// ═══════════════════════════════════════════════════════════════
//  KIRJAUSLOMAKE
//  Sama lomake kaavoittajalle ja viranomaistaholle: molemmat kirjaavat
//  samaan Sheetiin, avaimena (tunnus, taho).
// ═══════════════════════════════════════════════════════════════

function kenttaRivi(nimi, elementti) {
  const kaari = document.createElement("label");
  kaari.className = "pu-kentta";
  const teksti = document.createElement("span");
  teksti.textContent = nimi;
  kaari.appendChild(teksti);
  kaari.appendChild(elementti);
  return kaari;
}

/**
 * Yhden tallentajan muokattava lomake. Tallennus Apps Script -endpointin
 * kautta, joka avaa tai päivittää rivin avaimella (tunnus, taho) — muiden
 * kirjaukset eivät siis voi ylikirjoittua.
 *
 * Kaavoittajalla luokitus on esivalittuna Vastuumuseon pohja-arvoon, joten
 * pelkän kommentin tallentaminen vahvistaa museon kannan eikä tyhjennä sitä.
 */
function popupLomake(feature, tunnus, tallentaja) {
  const props      = feature.properties;
  const kaavoittaja = tallentaja.avain === KAAVOITTAJA.avain;
  const kanta      = kaavoittaja
    ? kaavoittajaKanta(props)
    : { arvot: viranomaisArvot(props, tallentaja.avain), oma: true };
  const arvot      = kanta.arvot;

  const el = osio(
    kaavoittaja ? "Kaavoittajan luokitus ja kommentti" : `Oma kommentti — ${tallentaja.nimi}`,
    "pu-vir pu-vir-lomake"
  );

  if (kaavoittaja && !kanta.oma && !kirjauksetLukittu()) {
    const vihje = document.createElement("p");
    vihje.className = "pu-pohja-vihje";
    vihje.textContent = "Luokka on vielä Vastuumuseon pohja — tallennus kirjaa sen omaksi kannaksi.";
    el.appendChild(vihje);
  }

  // ── Luokituspainikkeet ──
  let valittu = normalisoiLuokka(arvot[LUOKITUS_VIR]);
  const napitEl = document.createElement("div");
  napitEl.className = "pu-napit";
  const napit = LUOKAT.map(lk => {
    const nappi = document.createElement("button");
    nappi.type = "button";
    nappi.textContent = lk.selite;
    nappi.style.setProperty("--lk-vari", lk.vari);
    nappi.addEventListener("click", () => { valittu = lk.arvo; korosta(); });
    napitEl.appendChild(nappi);
    return { lk, nappi };
  });
  function korosta() {
    napit.forEach(({ lk, nappi }) => nappi.classList.toggle("aktiivinen", lk.arvo === valittu));
  }
  korosta();
  el.appendChild(napitEl);

  // ── Tekstikentät ──
  const muistetut = lueVirTiedot();

  const kommentti = document.createElement("textarea");
  kommentti.value = tyhja(arvot[KOMMENTTI_VIR]) ? "" : String(arvot[KOMMENTTI_VIR]);

  // Nimi omista tiedoista, ei Sheetistä: muuten kollegan nimi tulisi
  // esitäyttönä omaan kenttään ja kirjaus tallentuisi väärälle henkilölle
  const nimi = document.createElement("input");
  nimi.type  = "text";
  nimi.value = muistetut.nimi;

  el.appendChild(kenttaRivi(kaavoittaja ? "Perustelu / kommentti" : "Kommentti", kommentti));
  el.appendChild(kenttaRivi("Nimi", nimi));

  // ── Tallenna ──
  const jalkiosa = document.createElement("div");
  jalkiosa.className = "pu-lomake-footer";
  const tallenna = document.createElement("button");
  tallenna.type = "button";
  tallenna.textContent = "Tallenna";
  const viesti = document.createElement("span");
  viesti.className = "pu-lomake-viesti";
  jalkiosa.appendChild(tallenna);
  jalkiosa.appendChild(viesti);
  el.appendChild(jalkiosa);

  if (kirjauksetLukittu()) {
    // Lomake näkyy harmaana: luokka ja kommentti jäävät luettaviksi
    napit.forEach(({ nappi }) => { nappi.disabled = true; });
    kommentti.disabled = nimi.disabled = tallenna.disabled = true;
    nimi.value = "";
    const pvm = kirjauksetHaettu ? new Date(kirjauksetHaettu) : null;
    viesti.textContent = "Lausuntokierros on päättynyt, kirjauksia ei voi enää muuttaa"
      + (pvm && !isNaN(pvm) ? ` (tilanne ${pvm.toLocaleDateString("fi-FI")})` : "");
    return el;
  }

  const url = appsScriptUrl();
  if (!url) {
    // Hiljainen epäonnistuminen olisi pahin vaihtoehto: kirjaaja ei
    // tietäisi ettei mitään tallentunut minnekään.
    tallenna.disabled = true;
    viesti.className  = "pu-lomake-viesti virhe";
    viesti.textContent = "Tallennusta ei ole määritetty (apps_script_url puuttuu config.json:sta)";
    return el;
  }

  if (kirjauksetHaussa) {
    // Esitäyttö on vielä GeoJSONista. Popup piirtyy uudelleen, kun
    // Sheetin kirjaukset saapuvat (kirjauksetSaapuivat).
    napit.forEach(({ nappi }) => { nappi.disabled = true; });
    kommentti.disabled = nimi.disabled = tallenna.disabled = true;
    viesti.textContent = "Haetaan tallennettuja kirjauksia…";
    return el;
  }

  tallenna.addEventListener("click", async () => {
    const runko = {
      tunnus:          tunnus,
      [TAHO]:          tallentaja.nimi,
      [LUOKITUS_VIR]:  valittu,
      [KOMMENTTI_VIR]: kommentti.value.trim(),
      [NIMI_VIR]:      nimi.value.trim(),
    };

    tallenna.disabled  = true;
    viesti.className   = "pu-lomake-viesti";
    viesti.textContent = "Tallennetaan…";

    try {
      // text/plain, jotta selain ei tee OPTIONS-preflightiä —
      // Apps Script ei osaa vastata siihen.
      const resp = await fetch(url, {
        method:  "POST",
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        body:    JSON.stringify(runko),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.status !== "ok") throw new Error(data.message || "tuntematon virhe");

      // Tuore tila muistiin: väri ja lukuosio päivittyvät ilman uudelleenlatausta
      sheetsKommentit[kommenttiAvain(String(tunnus), tallentaja.avain)] = {
        tunnus:          String(tunnus),
        [TAHO]:          tallentaja.nimi,
        [LUOKITUS_VIR]:  runko[LUOKITUS_VIR],
        [KOMMENTTI_VIR]: runko[KOMMENTTI_VIR],
        [NIMI_VIR]:      runko[NIMI_VIR],
      };
      tallennaVirTiedot(runko[NIMI_VIR]);
      paivitaMarkkeri(tunnus, props);

      viesti.className   = "pu-lomake-viesti onnistui";
      viesti.textContent = data.toiminto === "paivitetty"
        ? "Tallennettu ✓ (päivitetty)" : "Tallennettu ✓";
    } catch (e) {
      viesti.className   = "pu-lomake-viesti virhe";
      viesti.textContent = `Tallennus epäonnistui: ${e.message}. Kirjausta EI tallennettu.`;
    } finally {
      tallenna.disabled = false;
    }
  });

  return el;
}

// ═══════════════════════════════════════════════════════════════
//  KIOSKI-TIEDOT
//  Museon Kioski 3.0 -rekisterin tiedot omana, oletuksena suljettuna
//  osionaan. Linkki vie Kioskiin, mutta toimii vain kirjautuneelle.
// ═══════════════════════════════════════════════════════════════

const KIOSKI_KENTAT = [
  ["merkittavyys",     "Merkittävyys"],
  ["arvot",            "Arvot"],
  ["valtakunnalliset", "Valtakunnalliset inventoinnit"],
  ["kuvaus",           "Kuvaus"],
  ["historia",         "Historia"],
  ["suojelutilanne",   "Suojelutilanne"],
  ["arviointi",        "Arviointi"],
  ["lahteet",          "Lähteet"],
];

function popupKioski(tunnus) {
  const k = kioskiData[tunnus];
  if (!k) return null;

  const rivit = KIOSKI_KENTAT
    .map(([avain, otsikko]) => {
      const arvo = Array.isArray(k[avain]) ? k[avain].join("\n") : k[avain];
      if (tyhja(arvo)) return "";
      // Rivinvaihdot säilyvät: suojelutilanteessa on kaava per rivi
      const teksti = esc(arvo).replace(/\n/g, "<br>");
      return `<tr><td>${esc(otsikko)}</td><td>${teksti}</td></tr>`;
    })
    .join("");

  const el = document.createElement("details");
  el.className = "pu-kioski";
  el.innerHTML = `
    <summary>Kioski: ${esc(k.nimi || "")}
      ${k.merkittavyys ? `<span class="pu-kioski-merk">· ${esc(k.merkittavyys)}</span>` : ""}
    </summary>
    <table>${rivit}</table>
    ${k.url ? `<a href="${esc(k.url)}" target="_blank" rel="noopener">Avaa Kioskissa (kohde ${esc(k.kohde_id)})</a>` : ""}`;
  return el;
}

function luoPopup(feature, layer) {
  const props  = feature.properties;
  const tunnus = String(props[TUNNUS] ?? "");

  const el = document.createElement("div");
  el.className = "pu";
  el.appendChild(popupOtsikko(props, tunnus));

  const kuvat = popupKuvat(props);
  if (kuvat) el.appendChild(kuvat);

  const attr = popupAttribuutit(props);
  if (attr) el.appendChild(attr);

  const kioski = popupKioski(tunnus);
  if (kioski) el.appendChild(kioski);

  const kaavoittajanNakyma = aktiivinen_nakyma === KAAVOITTAJA.avain;

  // ── Kaavoittajan kanta ──
  // Omassa näkymässään muokattavana, muissa yhden rivin lukuarvona.
  if (!kaavoittajanNakyma) el.appendChild(popupKaavoittajaLuku(props));

  // ── Viranomaisten kommentit ──
  // Kaikkien tahojen kannat näkyvät aina — myös kaavoittajan näkymässä, koska
  // lopullinen luokka muodostetaan niitä vasten.
  const taho = TAHOT.find(x => x.avain === aktiivinen_nakyma) || null;
  el.appendChild(popupViranomaisetLuku(props, taho ? taho.avain : null));

  if (kaavoittajanNakyma) {
    el.appendChild(popupLomake(feature, tunnus, KAAVOITTAJA));
  } else if (taho) {
    el.appendChild(popupLomake(feature, tunnus, taho));
  }

  return el;
}

// ═══════════════════════════════════════════════════════════════
//  NÄKYMÄVALITSIN JA LATAUSNAPPI
// ═══════════════════════════════════════════════════════════════

const NakymaControl = L.Control.extend({
  onAdd() {
    const div = L.DomUtil.create("div", "nakyma-control leaflet-bar");
    div.innerHTML = `
      <button data-nakyma="${esc(KAAVOITTAJA.avain)}" class="aktiivinen">Kaavoittajan luokitus</button>
      <span class="nakyma-otsake">Viranomaisen luokitus</span>
      ${TAHOT.map(taho =>
        `<button data-nakyma="${esc(taho.avain)}" class="nakyma-taho">${esc(taho.nimi)}</button>`
      ).join("")}
      <button id="lataa-suositukset" class="toiminto">Lataa kaavoittajan luokitus</button>`;
    L.DomEvent.disableClickPropagation(div);
    div.querySelectorAll("button[data-nakyma]").forEach(nappi => {
      nappi.addEventListener("click", () => vaihdaNakyma(nappi.dataset.nakyma));
    });
    div.querySelector("#lataa-suositukset")
       .addEventListener("click", lataaSuositukset);
    return div;
  },
});
new NakymaControl({ position: "topleft" }).addTo(map);

function vaihdaNakyma(nakyma) {
  aktiivinen_nakyma = nakyma;
  document.querySelectorAll(".nakyma-control button[data-nakyma]").forEach(nappi => {
    nappi.classList.toggle("aktiivinen", nappi.dataset.nakyma === nakyma);
  });
  map.closePopup();
  paivitaLayer();
}

// ═══════════════════════════════════════════════════════════════
//  SELITELAATIKKO
//  Kuusi luokkaa ei ole luettavissa pelkistä väreistä ilman selitettä.
//  Määrät kertovat samalla missä vaiheessa luokittelukierros on.
// ═══════════════════════════════════════════════════════════════

let selitysEl = null;

const SELITE_SADE = 6;

/**
 * Selitteen merkki piirretään samalla funktiolla kuin karttasymboli, jotta
 * kuviot vastaavat toisiaan. Merkit näytetään aina oman kirjauksen asussa
 * (täytettyinä, paksulla viivalla) — pohja-arvon ohuempi asu on kartalla
 * ohimenevä tila, ei oma luokkansa.
 */
function selitysMerkki(lk) {
  return symboliSvg({
    muoto:  lk.muoto || "rengas",
    vari:   lk.vari,
    viiva:  2.5 + (lk.paksuusero || 0),
    katko:  lk.katko || "",
    tayttö: true,
  }, 16, SELITE_SADE);
}

const SelitysControl = L.Control.extend({
  onAdd() {
    const div = L.DomUtil.create("div", "selitys leaflet-bar");
    L.DomEvent.disableClickPropagation(div);
    selitysEl = div;
    paivitaSelitys();
    return div;
  },
});
new SelitysControl({ position: "bottomleft" }).addTo(map);

function paivitaSelitys() {
  if (!selitysEl) return;
  const maarat = new Map(LUOKAT.map(lk => [lk.arvo, 0]));

  (geojsonData ? geojsonData.features : []).forEach(f => {
    const arvo = normalisoiLuokka(nykyinenKanta(f.properties).arvot[LUOKITUS_VIR]);
    maarat.set(arvo, (maarat.get(arvo) || 0) + 1);
  });

  // Tyhjä arvo esiintyy vain viranomaisnäkymissä (ei vielä kommentoinut).
  // Se ei ole valittava luokka, mutta rivi tarvitaan jotta määrät täsmäävät
  // kohteiden lukumäärään.
  const nakyvat = maarat.get(EI_KIRJAUSTA.arvo)
    ? [...LUOKAT, EI_KIRJAUSTA]
    : LUOKAT;

  const rivit = nakyvat.map(lk => {
    const n = maarat.get(lk.arvo) || 0;
    return `<li${n ? "" : ' class="tyhja"'}>
        ${selitysMerkki(lk)}
        <span class="selitys-teksti">${esc(lk.selite)}</span>
        <span class="selitys-maara">${n}</span>
      </li>`;
  }).join("");

  // Määrät ovat alustavia, kunnes Sheetin kirjaukset ovat tulleet
  const haussa = kirjauksetHaussa
    ? '<p class="selitys-haussa">Haetaan kirjauksia…</p>' : "";
  selitysEl.innerHTML = `<ul class="selitys-lista">${rivit}</ul>${haussa}`;
}

// ═══════════════════════════════════════════════════════════════
//  LATAA KAAVOITTAJAN LUOKITUS
//  Vie jokaiselle kohteelle voimassa olevan luokan — myös museon pohjasta
//  perityn — jotta pipelinen tila 3 kirjoittaa GeoPackageen täyden
//  näkemyksen eikä vain muutettuja kohteita.
// ═══════════════════════════════════════════════════════════════

function lataaSuositukset() {
  if (!geojsonData) {
    alert("Aineistoa ei ole vielä ladattu.");
    return;
  }

  const kopio = JSON.parse(JSON.stringify(geojsonData));
  let omia = 0;
  kopio.features.forEach(f => {
    const { arvot, oma } = kaavoittajaKanta(f.properties);
    f.properties[LUOKITUS]                        = arvot[LUOKITUS_VIR];
    f.properties[virSarake("kommentti", KAAVOITTAJA.avain)] = arvot[KOMMENTTI_VIR] || "";
    f.properties[virSarake("nimi", KAAVOITTAJA.avain)]      = arvot[NIMI_VIR] || "";
    if (oma) omia++;
  });

  const pvm  = new Date().toISOString().slice(0, 10);
  const nimi = `kaavoittajan_luokitus_${PROJEKTI}_${pvm}.geojson`;
  const blob = new Blob([JSON.stringify(kopio)], { type: "application/geo+json" });
  const url  = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = nimi;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  console.log(`Ladattu ${nimi} — ${omia}/${kopio.features.length} kaavoittajan omaa kirjausta`);
}

// ═══════════════════════════════════════════════════════════════
//  LIGHTBOX
// ═══════════════════════════════════════════════════════════════

function avaaLightbox(url) {
  document.getElementById("lightbox-kuva").src = url;
  document.getElementById("lightbox").classList.add("auki");
}
function suljeLightbox() {
  document.getElementById("lightbox").classList.remove("auki");
}
document.getElementById("lightbox-sulje").addEventListener("click", suljeLightbox);
document.getElementById("lightbox").addEventListener("click", e => {
  if (e.target === e.currentTarget) suljeLightbox();
});
document.addEventListener("keydown", e => { if (e.key === "Escape") suljeLightbox(); });

// ═══════════════════════════════════════════════════════════════
//  INIT — projekti window.PROJEKTI:stä tai URL-parametrista
// ═══════════════════════════════════════════════════════════════

async function init() {
  PROJEKTI = window.PROJEKTI || new URLSearchParams(window.location.search).get("projekti");
  if (!PROJEKTI) {
    document.body.insertAdjacentHTML("afterbegin",
      '<p style="padding:1em;color:red">Puuttuu URL-parametri: <strong>?projekti=nimi</strong></p>');
    return;
  }

  try {
    projektiConfig = await haeData("config.json");
  } catch (e) {
    console.warn("config.json puuttuu, jatketaan oletuksilla:", e.message);
  }

  (projektiConfig.tasot || []).forEach(taso => {
    const layer = L.tileLayer.wms(taso.url, {
      layers:      taso.layer,
      format:      "image/png",
      transparent: true,
      version:     "1.1.1",
      // GeoServer ei lähetä cache-control- eikä etag-otsakkeita, joten selain
      // ei voi tallentaa laattoja välimuistiin: sama alue haetaan uudelleen
      // joka zoomauksella. Pyyntöjen määrä on siksi ainoa vipu.
      //   • 1024 px laatta = neljäsosa pyynnöistä 512:een verrattuna
      //   • updateWhenZooming/updateWhenIdle: ei pyyntöjä välizoomeille eikä
      //     kesken panoroinnin, vain kun kartta pysähtyy
      //   • keepBuffer: näkymän ulkopuoliset laatat säilyvät pidempään,
      //     joten panorointi takaisin ei hae niitä uudelleen
      tileSize:          1024,
      updateWhenZooming: false,
      updateWhenIdle:    true,
      keepBuffer:        4,
    });
    layer.on("add", () => {
      layer.getContainer().style.mixBlendMode = "multiply";
    });
    if (taso.nakyva !== false) layer.addTo(map);
    layerControl.addOverlay(layer, taso.nimi);
  });

  // Sheetin nykytila (kaavoittajan omat kirjaukset ja Vastuumuseon
  // pohja-arvot) haetaan taustalla. Kohteet piirretään sitä odottamatta,
  // ja symbolit päivittyvät kirjausten saavuttua.
  if (appsScriptUrl() || kirjauksetLukittu()) {
    kirjauksetHaussa = true;
    const nappi = document.getElementById("lataa-suositukset");
    if (nappi) nappi.disabled = true;
  }
  const kirjaukset = haeKommentit();

  // Kioski-tiedot ennen piirtoa, jotta ne ovat mukana ensimmäisissä popupeissa
  const [geo] = await Promise.allSettled([
    haeData("data/kohteet.geojson"),
    haeData("data/kioski.json")
      .then(d => { kioskiData = d || {}; })
      .catch(() => { kioskiData = {}; }),   // ei Kioski-tietoja tässä projektissa
  ]);

  if (geo.status === "fulfilled") {
    geojsonData = geo.value;
    paivitaLayer();
    if (geojsonLayer && geojsonLayer.getBounds().isValid()) {
      // maxZoom: yhden kohteen projektissa rajaus on nollan kokoinen ja
      // Leaflet laskisi zoomiksi äärettömän ("infinite number of tiles").
      map.fitBounds(geojsonLayer.getBounds(), { padding: [40, 40], maxZoom: 13 });
    }
  } else {
    console.error("GeoJSON-lataus epäonnistui:", geo.reason);
  }

  // haeKommentit ei heitä: epäonnistunut haku jättää GeoJSONin arvot voimaan
  await kirjaukset;
  kirjauksetSaapuivat();
}

init();
