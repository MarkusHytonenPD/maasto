"use strict";

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

const layerControl = L.control.layers(
  { "Maastokartta": mmlMaasto, "Taustakartta": mmlTausta },
  {},
  { collapsed: false }
).addTo(map);

// ═══════════════════════════════════════════════════════════════
//  LUOKITUSMALLI
//  Sama kolmiportainen asteikko kaavoittajalle ja viranomaiselle.
//  arvo = se merkkijono joka on GeoPackagessa ja Sheetsissä.
// ═══════════════════════════════════════════════════════════════

const LUOKAT = [
  // Harmaa on tummempi kuin popupin harmaat tekstit: ääriviivana vaalea
  // harmaa hukkui maastokartan viivastoon
  { arvo: "",             selite: "Ei merkintää",             vari: "#555555" },
  { arvo: "paikallinen",  selite: "Suositus säilyttämisestä", vari: "#1f78b4" },
  { arvo: "suojelukohde", selite: "Suojelukohde",             vari: "#e31a1c" },
];

// Aineistossa esiintyvä "ei arvoja" tarkoittaa samaa kuin tyhjä.
const TYHJAT = ["", "ei arvoja", "0", "null", "none", "nan"];

const TUNNUS         = "tunnus";
const LUOKITUS       = "potentiaali";      // kaavoittajan suositus
const LUOKITUS_VIR   = "luokitus_vir";
const KOMMENTTI_VIR  = "kommentti_vir";
const NIMI_VIR       = "nimi_vir";
const VIRASTO_VIR    = "virasto_vir";
const KUVAT          = ["kuva1", "kuva2", "kuva3"];

// Sarakkeiden näyttöotsikot. Muut sarakkeet näytetään omalla nimellään.
const OTSIKOT = {
  [LUOKITUS]:      "Kaavoittajan suositus",
  [LUOKITUS_VIR]:  "Viranomaisen luokitus",
  [KOMMENTTI_VIR]: "Kommentti",
  [NIMI_VIR]:      "Nimi",
  [VIRASTO_VIR]:   "Virasto",
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
  return l ? l.vari : LUOKAT[0].vari;
}

// ═══════════════════════════════════════════════════════════════
//  TILA
// ═══════════════════════════════════════════════════════════════

let PROJEKTI        = "";
let projektiConfig  = {};
let geojsonData     = null;
let geojsonLayer    = null;
let aktiivinen_nakyma = "kaavoittaja";     // "kaavoittaja" | "viranomainen"
const markkerit     = {};                  // tunnus → layer

// Kaavoittajan selaimessa tekemät muutokset: { tunnus: arvo }
let kenttaMuutokset = {};

// Sheetsistä haetut viranomaislausunnot: { tunnus: {luokitus_vir, ...} }
// Nämä ovat tuoreempia kuin GeoJSONin arvot, jotka päivittyvät vain
// pipeline-ajossa — ilman tätä toinen viranomainen ei näkisi ensimmäisen
// kirjaamaa lausuntoa ja voisi ylikirjoittaa sen.
let sheetsLausunnot = {};

const VIR_TIEDOT_AVAIN = "viranomainen_tiedot";   // nimi ja virasto muistiin

function muutosAvain() {
  return `luokitukset_kentta_${PROJEKTI}`;
}

function lataaMuutokset() {
  try {
    kenttaMuutokset = JSON.parse(localStorage.getItem(muutosAvain()) || "{}");
  } catch (e) {
    console.warn("localStorage-luku epäonnistui:", e);
    kenttaMuutokset = {};
  }
}

function tallennaMuutokset() {
  try {
    localStorage.setItem(muutosAvain(), JSON.stringify(kenttaMuutokset));
  } catch (e) {
    console.warn("localStorage-tallennus epäonnistui:", e);
  }
}

/** Kaavoittajan suositus: selaimen muutos voittaa GeoJSONin arvon. */
function kenttaLuokitus(props) {
  const tunnus = String(props[TUNNUS] ?? "");
  if (Object.prototype.hasOwnProperty.call(kenttaMuutokset, tunnus)) {
    return kenttaMuutokset[tunnus];
  }
  return props[LUOKITUS];
}

/** Viranomaisen lausunto: Sheetsin tuore rivi voittaa GeoJSONin arvot. */
function viranomaisArvot(props) {
  const tunnus = String(props[TUNNUS] ?? "");
  const rivi   = sheetsLausunnot[tunnus];
  if (rivi) return rivi;
  return {
    [LUOKITUS_VIR]:  props[LUOKITUS_VIR],
    [KOMMENTTI_VIR]: props[KOMMENTTI_VIR],
    [NIMI_VIR]:      props[NIMI_VIR],
    [VIRASTO_VIR]:   props[VIRASTO_VIR],
  };
}

function appsScriptUrl() {
  const url = projektiConfig.apps_script_url;
  return tyhja(url) ? "" : String(url).trim();
}

/** Hakee Sheetin nykytilan Apps Scriptin doGet-rajapinnasta. */
async function haeLausunnot() {
  const url = appsScriptUrl();
  if (!url) return;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.status !== "ok" || !Array.isArray(data.rivit)) {
      throw new Error(data.message || "odottamaton vastaus");
    }
    sheetsLausunnot = {};
    data.rivit.forEach(r => {
      const tunnus = String(r.tunnus ?? "").trim();
      if (tunnus) sheetsLausunnot[tunnus] = r;
    });
    console.log(`Viranomaislausuntoja Sheetsistä: ${Object.keys(sheetsLausunnot).length}`);
  } catch (e) {
    // Kartta toimii ilman tätäkin — GeoJSONin arvot ovat silloin käytössä
    console.warn("Lausuntojen haku Sheetsistä epäonnistui:", e);
  }
}

/** Muistaa viranomaisen nimen ja viraston, jottei niitä kirjoiteta uudelleen. */
function lueVirTiedot() {
  try {
    const tiedot = JSON.parse(localStorage.getItem(VIR_TIEDOT_AVAIN) || "{}");
    return { nimi: tiedot.nimi || "", virasto: tiedot.virasto || "" };
  } catch (e) {
    return { nimi: "", virasto: "" };
  }
}

function tallennaVirTiedot(nimi, virasto) {
  try {
    localStorage.setItem(VIR_TIEDOT_AVAIN, JSON.stringify({ nimi, virasto }));
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

/** Popupissa näytettävät attribuuttisarakkeet config.json:sta. */
function naytettavatSarakkeet(props) {
  const valitut = projektiConfig.naytettavat_sarakkeet;
  if (Array.isArray(valitut) && valitut.length) {
    return valitut.filter(s => s in props);
  }
  // Ei valintaa configissa — näytetään kaikki paitsi erikseen esitetyt
  const piilota = new Set([LUOKITUS, LUOKITUS_VIR, KOMMENTTI_VIR, NIMI_VIR, VIRASTO_VIR, ...KUVAT]);
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

function pisteVari(props) {
  return aktiivinen_nakyma === "kaavoittaja"
    ? luokkaVari(kenttaLuokitus(props))
    : luokkaVari(viranomaisArvot(props)[LUOKITUS_VIR]);
}

const MARKKERI_SADE = 14;

function markerTyyli(props) {
  const vari = pisteVari(props);
  return {
    radius: MARKKERI_SADE,
    // Väritys ääriviivassa, ei täytössä — kaavarasteri näkyy symbolin läpi
    color: vari,
    weight: 3,
    opacity: 1,
    // Ei täyttöä lainkaan. Klikattavuus hoidetaan kartta.css:n
    // pointer-events-säännöllä, ei näkymättömällä täytöllä: Chrome ei pidä
    // fill-opacity: 0 -täyttöä maalattuna, joten klikkaus menisi läpi.
    fill: false,
  };
}

function luoMarker(feature, latlng) {
  return L.circleMarker(latlng, markerTyyli(feature.properties));
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
}

/** Päivittää yhden pisteen värin ilman että popup sulkeutuu. */
function paivitaMarkkeri(tunnus, props) {
  const layer = markkerit[String(tunnus)];
  if (layer && layer.setStyle) layer.setStyle(markerTyyli(props));
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

/** Kaavoittajan luokitusnapit. Muutos tallentuu localStorageen. */
function popupLuokitusNapit(feature, tunnus) {
  const props = feature.properties;
  const el = document.createElement("div");
  el.className = "pu-napit";

  const napit = LUOKAT.map(lk => {
    const nappi = document.createElement("button");
    nappi.type = "button";
    nappi.textContent = lk.selite;
    nappi.style.setProperty("--lk-vari", lk.vari);
    nappi.addEventListener("click", () => {
      kenttaMuutokset[String(tunnus)] = lk.arvo;
      tallennaMuutokset();
      paivitaMarkkeri(tunnus, props);
      korosta();
    });
    el.appendChild(nappi);
    return { lk, nappi };
  });

  function korosta() {
    const nyt = normalisoiLuokka(kenttaLuokitus(props));
    napit.forEach(({ lk, nappi }) => {
      nappi.classList.toggle("aktiivinen", lk.arvo === nyt);
    });
  }
  korosta();
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

/** Viranomaisen lausunto — vain luku. */
function popupViranomainenLuku(props) {
  const el     = osio("Viranomaisen lausunto", "pu-vir");
  const arvot  = viranomaisArvot(props);

  const kentat = [
    [LUOKITUS_VIR,  luokkaSelite(arvot[LUOKITUS_VIR])],
    [KOMMENTTI_VIR, arvot[KOMMENTTI_VIR]],
    [NIMI_VIR,      arvot[NIMI_VIR]],
    [VIRASTO_VIR,   arvot[VIRASTO_VIR]],
  ].filter(([sarake, arvo]) => !tyhja(arvot[sarake]) && !tyhja(arvo));

  if (!kentat.length) {
    const p = document.createElement("p");
    p.className = "pu-vir-tyhja";
    p.textContent = "Ei viranomaislausuntoa";
    el.appendChild(p);
    return el;
  }

  const taulu = document.createElement("div");
  taulu.className = "pu-attr";
  taulu.innerHTML = `<table>${kentat
    .map(([sarake, arvo]) => `<tr><td>${esc(otsikko(sarake))}</td><td>${esc(arvo)}</td></tr>`)
    .join("")}</table>`;
  el.appendChild(taulu);

  const lk = luokka(arvot[LUOKITUS_VIR]);
  if (lk) {
    el.style.borderLeftColor = lk.vari;
  }
  return el;
}

// ═══════════════════════════════════════════════════════════════
//  VIRANOMAISEN LOMAKE
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

/** Viranomaisen muokattava lomake. Tallennus Apps Script -endpointin kautta. */
function popupViranomainenLomake(feature, tunnus) {
  const props = feature.properties;
  const arvot = viranomaisArvot(props);
  const el    = osio("Viranomaisen lausunto", "pu-vir pu-vir-lomake");

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

  const nimi = document.createElement("input");
  nimi.type  = "text";
  nimi.value = !tyhja(arvot[NIMI_VIR]) ? String(arvot[NIMI_VIR]) : muistetut.nimi;

  const virasto = document.createElement("input");
  virasto.type  = "text";
  virasto.value = !tyhja(arvot[VIRASTO_VIR]) ? String(arvot[VIRASTO_VIR]) : muistetut.virasto;

  el.appendChild(kenttaRivi("Kommentti", kommentti));
  el.appendChild(kenttaRivi("Nimi", nimi));
  el.appendChild(kenttaRivi("Virasto", virasto));

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

  const url = appsScriptUrl();
  if (!url) {
    // Hiljainen epäonnistuminen olisi pahin vaihtoehto: viranomainen ei
    // tietäisi ettei lausunto tallentunut minnekään.
    tallenna.disabled = true;
    viesti.className  = "pu-lomake-viesti virhe";
    viesti.textContent = "Tallennusta ei ole määritetty (apps_script_url puuttuu config.json:sta)";
    return el;
  }

  tallenna.addEventListener("click", async () => {
    const runko = {
      tunnus:            tunnus,
      [LUOKITUS_VIR]:    valittu,
      [KOMMENTTI_VIR]:   kommentti.value.trim(),
      [NIMI_VIR]:        nimi.value.trim(),
      [VIRASTO_VIR]:     virasto.value.trim(),
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
      sheetsLausunnot[String(tunnus)] = {
        tunnus:          String(tunnus),
        [LUOKITUS_VIR]:  runko[LUOKITUS_VIR],
        [KOMMENTTI_VIR]: runko[KOMMENTTI_VIR],
        [NIMI_VIR]:      runko[NIMI_VIR],
        [VIRASTO_VIR]:   runko[VIRASTO_VIR],
      };
      tallennaVirTiedot(runko[NIMI_VIR], runko[VIRASTO_VIR]);
      paivitaMarkkeri(tunnus, props);

      viesti.className   = "pu-lomake-viesti onnistui";
      viesti.textContent = data.toiminto === "paivitetty"
        ? "Lausunto päivitetty ✓" : "Lausunto tallennettu ✓";
    } catch (e) {
      viesti.className   = "pu-lomake-viesti virhe";
      viesti.textContent = `Tallennus epäonnistui: ${e.message}. Lausuntoa EI tallennettu.`;
    } finally {
      tallenna.disabled = false;
    }
  });

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

  // ── Kaavoittajan suositus ──
  if (aktiivinen_nakyma === "kaavoittaja") {
    const kaava = osio("Kaavoittajan suositus", "pu-kaava");
    kaava.appendChild(popupLuokitusNapit(feature, tunnus));
    el.appendChild(kaava);
  } else {
    // Yhdelle riville: viranomaisnäkymässä pystytila tarvitaan lomakkeelle,
    // jotta Tallenna-nappi näkyy ilman popupin vierittämistä.
    const kaava = document.createElement("div");
    kaava.className = "pu-kaava pu-kaava-luku";
    const otsake = document.createElement("span");
    otsake.className = "pu-kaava-otsake";
    otsake.textContent = "Kaavoittajan suositus:";
    const arvo = document.createElement("span");
    arvo.className = "pu-lukuarvo";
    arvo.textContent = luokkaSelite(kenttaLuokitus(props));
    kaava.appendChild(otsake);
    kaava.appendChild(arvo);
    el.appendChild(kaava);
  }

  // ── Viranomaisen lausunto: muokattava vain viranomaisnäkymässä ──
  el.appendChild(aktiivinen_nakyma === "viranomainen"
    ? popupViranomainenLomake(feature, tunnus)
    : popupViranomainenLuku(props));

  return el;
}

// ═══════════════════════════════════════════════════════════════
//  NÄKYMÄVALITSIN JA LATAUSNAPPI
// ═══════════════════════════════════════════════════════════════

const NakymaControl = L.Control.extend({
  onAdd() {
    const div = L.DomUtil.create("div", "nakyma-control leaflet-bar");
    div.innerHTML = `
      <button id="nakyma-kaavoittaja" class="aktiivinen">Kaavoittajan suositus</button>
      <button id="nakyma-viranomainen">Viranomaisen luokitus</button>
      <button id="lataa-suositukset" class="toiminto">Lataa kaavoittajan suositukset</button>`;
    L.DomEvent.disableClickPropagation(div);
    div.querySelector("#nakyma-kaavoittaja")
       .addEventListener("click", () => vaihdaNakyma("kaavoittaja"));
    div.querySelector("#nakyma-viranomainen")
       .addEventListener("click", () => vaihdaNakyma("viranomainen"));
    div.querySelector("#lataa-suositukset")
       .addEventListener("click", lataaSuositukset);
    return div;
  },
});
new NakymaControl({ position: "topleft" }).addTo(map);

function vaihdaNakyma(nakyma) {
  aktiivinen_nakyma = nakyma;
  document.getElementById("nakyma-kaavoittaja")
          .classList.toggle("aktiivinen", nakyma === "kaavoittaja");
  document.getElementById("nakyma-viranomainen")
          .classList.toggle("aktiivinen", nakyma === "viranomainen");
  map.closePopup();
  paivitaLayer();
}

// ═══════════════════════════════════════════════════════════════
//  LATAA KAAVOITTAJAN SUOSITUKSET
// ═══════════════════════════════════════════════════════════════

function lataaSuositukset() {
  if (!geojsonData) {
    alert("Aineistoa ei ole vielä ladattu.");
    return;
  }

  const kopio = JSON.parse(JSON.stringify(geojsonData));
  let muutettu = 0;
  kopio.features.forEach(f => {
    const tunnus = String(f.properties[TUNNUS] ?? "");
    if (Object.prototype.hasOwnProperty.call(kenttaMuutokset, tunnus)) {
      f.properties[LUOKITUS] = kenttaMuutokset[tunnus];
      muutettu++;
    }
  });

  const pvm  = new Date().toISOString().slice(0, 10);
  const nimi = `kaavoittajan_suositus_${PROJEKTI}_${pvm}.geojson`;
  const blob = new Blob([JSON.stringify(kopio)], { type: "application/geo+json" });
  const url  = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = nimi;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  console.log(`Ladattu ${nimi} — ${muutettu} muutettua luokitusta`);
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

  lataaMuutokset();

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

  // Sheetin nykytila ennen ensimmäistä piirtoa, jotta viranomaisnäkymän
  // värit ja lomakkeen esitäyttö perustuvat tuoreeseen dataan.
  await haeLausunnot();

  try {
    geojsonData = await haeData("data/kohteet.geojson");
    paivitaLayer();
    if (geojsonLayer && geojsonLayer.getBounds().isValid()) {
      // maxZoom: yhden kohteen projektissa rajaus on nollan kokoinen ja
      // Leaflet laskisi zoomiksi äärettömän ("infinite number of tiles").
      map.fitBounds(geojsonLayer.getBounds(), { padding: [40, 40], maxZoom: 13 });
    }
  } catch (e) {
    console.error("GeoJSON-lataus epäonnistui:", e);
  }
}

init();
