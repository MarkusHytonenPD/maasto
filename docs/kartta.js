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
//  TILA
// ═══════════════════════════════════════════════════════════════

const TUNNUS = "tunnus";

const OMA_VARIT = {
  "A+": "#e31a1c",
  "A":  "#ff7f00",
  "B":  "#ffd700",
  "C":  "#999999",
};

const VIR_VARIT = {
  "Suojelukohde":        "#e31a1c",
  "Huomionarvoinen":     "#ff7f00",
  "Ei erityisiä arvoja": "#999999",
};
const VIR_CSS = {
  "Suojelukohde":        "lk-suojelukohde",
  "Huomionarvoinen":     "lk-huomionarvoinen",
  "Ei erityisiä arvoja": "lk-ei-arvoja",
};

let aktiivinen_teema = "oma";
let sheetsData = null;
let geojsonData = null;
let geojsonLayer = null;
const featureData = {};

// ═══════════════════════════════════════════════════════════════
//  TEEMOITUS
// ═══════════════════════════════════════════════════════════════

function viimeisinLuokitus(tunnus) {
  const rivit = (sheetsData || {})[tunnus];
  return rivit && rivit.length ? rivit[rivit.length - 1].luokitus : null;
}

function pisteVari(props) {
  const tunnus = props[TUNNUS];
  if (aktiivinen_teema === "oma") {
    return OMA_VARIT[props.luokitus] || "#1f78b4";
  }
  const lk = viimeisinLuokitus(tunnus);
  return lk ? (VIR_VARIT[lk] || "#999999") : null;
}

function luoMarker(feature, latlng) {
  const props = feature.properties;
  const vari = pisteVari(props);

  if (vari === null) {
    return L.marker(latlng, {
      icon: L.divIcon({
        html: '<div style="width:16px;height:16px;border-radius:50%;background:white;border:2px solid #444;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:bold;line-height:1">?</div>',
        className: "",
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      }),
    });
  }

  return L.circleMarker(latlng, {
    radius: 7,
    fillColor: vari,
    color: "#fff",
    weight: 1,
    opacity: 1,
    fillOpacity: 0.85,
  });
}

function paivitaLayer() {
  if (!geojsonData) return;
  if (geojsonLayer) map.removeLayer(geojsonLayer);
  geojsonLayer = L.geoJSON(geojsonData, {
    pointToLayer: luoMarker,
    onEachFeature(feature, layer) {
      featureData[feature.properties[TUNNUS]] = feature;
      layer.on("click", () => avaaPopup(feature, layer));
    },
  }).addTo(map);
}

// ═══════════════════════════════════════════════════════════════
//  SHEETS-DATA
// ═══════════════════════════════════════════════════════════════

async function haeKaikkiSheets() {
  if (sheetsData !== null) return;
  try {
    const resp = await fetch(CONFIG.SHEETS_URL);
    const rivit = await resp.json();
    sheetsData = {};
    for (const r of rivit) {
      (sheetsData[r.tunnus] = sheetsData[r.tunnus] || []).push(r);
    }
  } catch (e) {
    console.warn("Sheets-haku (kaikki) epäonnistui:", e);
    sheetsData = {};
  }
}

async function paivitaSheetsYhdelle(tunnus) {
  try {
    const resp = await fetch(`${CONFIG.SHEETS_URL}?tunnus=${encodeURIComponent(tunnus)}`);
    const rivit = await resp.json();
    if (!sheetsData) sheetsData = {};
    sheetsData[tunnus] = rivit;
    return rivit;
  } catch (e) {
    return null;
  }
}

// ═══════════════════════════════════════════════════════════════
//  POPUP
// ═══════════════════════════════════════════════════════════════

const OHITA_KENTAT = new Set(["kuva1", "kuva2", "kuva3"]);

function popupKuvat(props) {
  const kuvat = [props.kuva1, props.kuva2, props.kuva3].filter(Boolean);
  if (!kuvat.length) return "";
  return `<div class="pu-kuvat">${kuvat.map(url =>
    `<img src="${url}" alt="kuva" onclick="avaaLightbox('${url}')" />`
  ).join("")}</div>`;
}

function popupAttribuutit(props) {
  const rivit = Object.entries(props)
    .filter(([k, v]) => !OHITA_KENTAT.has(k) && v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("");
  return rivit ? `<div class="pu-attr"><table>${rivit}</table></div>` : "";
}

function popupViranomainenHTML(tunnus) {
  const rivit = (sheetsData || {})[tunnus] || [];
  const uusin = rivit[rivit.length - 1];
  if (!uusin) {
    return `<div class="pu-viranomainen">Ei viranomaisen luokitusta</div>`;
  }
  const css = VIR_CSS[uusin.luokitus] || "";
  return `<div class="pu-viranomainen ${css}"><strong>${uusin.luokitus}</strong></div>`;
}

function popupKommentitHTML(tunnus) {
  const rivit = (sheetsData || {})[tunnus] || [];
  if (!rivit.length) {
    return `<p class="pu-ei-kommentteja">Ei kommentteja.</p>`;
  }
  return rivit.map(r => `
    <div class="pu-kommentti">
      <div>${r.kommentti || ""}</div>
      <div class="pu-kommentti-meta">${[r.tekija, r.paivamaara, r.luokitus].filter(Boolean).join(" · ")}</div>
    </div>`).join("");
}

async function avaaPopup(feature, layer) {
  const props  = feature.properties;
  const tunnus = props[TUNNUS] || "";
  const nimi   = props.nimi || props.name || tunnus;

  const html = `
    <div class="pu">
      <div class="pu-otsikko">${nimi} <span class="pu-tunnus">(${tunnus})</span></div>
      ${popupKuvat(props)}
      ${popupAttribuutit(props)}
      <div class="pu-kommentit">
        <h4>Viranomaisen luokitus</h4>
        <div id="pu-vir-${tunnus}" class="pu-viranomainen">Ladataan…</div>
        <h4>Kommentit</h4>
        <div id="pu-kom-${tunnus}">Ladataan…</div>
      </div>
      <div class="pu-lomake">
        <h4>Lisää kommentti</h4>
        <label>Kommentti</label>
        <textarea id="lom-kom-${tunnus}"></textarea>
        <label>Nimi / virasto</label>
        <input type="text" id="lom-tek-${tunnus}" />
        <label>Luokitus</label>
        <select id="lom-lk-${tunnus}">
          <option>Ei erityisiä arvoja</option>
          <option>Huomionarvoinen</option>
          <option>Suojelukohde</option>
        </select>
        <div class="pu-lomake-footer">
          <button onclick="lahetaKommentti('${tunnus}')">Tallenna</button>
          <span class="pu-lomake-viesti" id="lom-viesti-${tunnus}"></span>
        </div>
      </div>
    </div>`;

  layer.bindPopup(html, { maxWidth: 440, maxHeight: 520, autoPan: true }).openPopup();

  const rivit = await paivitaSheetsYhdelle(tunnus);
  const vEl = document.getElementById(`pu-vir-${tunnus}`);
  const kEl = document.getElementById(`pu-kom-${tunnus}`);
  if (rivit !== null) {
    if (vEl) vEl.outerHTML = popupViranomainenHTML(tunnus);
    if (kEl) kEl.innerHTML = popupKommentitHTML(tunnus);
  } else {
    if (kEl) kEl.innerHTML = `<span style="color:red;font-size:11px">Sheets-haku epäonnistui</span>`;
  }
}

async function lahetaKommentti(tunnus) {
  const kommentti = document.getElementById(`lom-kom-${tunnus}`).value.trim();
  const tekija    = document.getElementById(`lom-tek-${tunnus}`).value.trim();
  const luokitus  = document.getElementById(`lom-lk-${tunnus}`).value;
  const viestiEl  = document.getElementById(`lom-viesti-${tunnus}`);
  const nimi      = (featureData[tunnus] || {}).properties?.nimi || "";

  if (!kommentti) { viestiEl.textContent = "Kirjoita kommentti."; return; }

  viestiEl.textContent = "Tallennetaan…";
  try {
    const resp = await fetch(CONFIG.SHEETS_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: JSON.stringify({ tunnus, kommentti, tekija, luokitus, rakennus_nimi: nimi }),
    });
    if (!resp.ok) throw new Error(resp.status);

    viestiEl.textContent = "Tallennettu ✓";
    document.getElementById(`lom-kom-${tunnus}`).value = "";

    await paivitaSheetsYhdelle(tunnus);
    const kEl = document.getElementById(`pu-kom-${tunnus}`);
    if (kEl) kEl.innerHTML = popupKommentitHTML(tunnus);
  } catch (e) {
    viestiEl.textContent = "Virhe tallennuksessa.";
  }
}

// ═══════════════════════════════════════════════════════════════
//  TEEMAPAINIKKEET
// ═══════════════════════════════════════════════════════════════

const TeemaControl = L.Control.extend({
  onAdd() {
    const div = L.DomUtil.create("div", "teema-control leaflet-bar");
    div.innerHTML = `
      <button id="teema-oma"          class="aktiivinen">Oma luokitus</button>
      <button id="teema-viranomainen"              >Viranomaisen luokitus</button>`;
    L.DomEvent.disableClickPropagation(div);
    div.querySelector("#teema-oma").addEventListener("click", () => vaihdaTeema("oma"));
    div.querySelector("#teema-viranomainen").addEventListener("click", () => vaihdaTeema("viranomainen"));
    return div;
  },
});
new TeemaControl({ position: "topleft" }).addTo(map);

async function vaihdaTeema(teema) {
  aktiivinen_teema = teema;
  document.getElementById("teema-oma").classList.toggle("aktiivinen", teema === "oma");
  document.getElementById("teema-viranomainen").classList.toggle("aktiivinen", teema === "viranomainen");
  if (teema === "viranomainen") await haeKaikkiSheets();
  paivitaLayer();
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
  const projekti = window.PROJEKTI || new URLSearchParams(window.location.search).get("projekti");
  if (!projekti) {
    document.body.insertAdjacentHTML("afterbegin",
      '<p style="padding:1em;color:red">Puuttuu URL-parametri: <strong>?projekti=nimi</strong></p>');
    return;
  }

  let projektiConfig = { tasot: [] };
  try {
    const r = await fetch(`${CONFIG.GITHUB_RAW}/projektit/${projekti}/config.json`);
    if (r.ok) projektiConfig = await r.json();
  } catch (e) {
    console.warn("config.json puuttuu, jatketaan ilman tasoja");
  }

  (projektiConfig.tasot || []).forEach(taso => {
    const layer = L.tileLayer.wms(taso.url, {
      layers:      taso.layer,
      format:      "image/png",
      transparent: true,
      version:     "1.1.1",
      tileSize:    512,
    });
    layer.on("add", () => {
      layer.getContainer().style.mixBlendMode = "multiply";
    });
    if (taso.nakyva !== false) layer.addTo(map);
    layerControl.addOverlay(layer, taso.nimi);
  });

  const geojsonUrl = `${CONFIG.GITHUB_RAW}/projektit/${projekti}/data/kohteet.geojson`;
  fetch(geojsonUrl)
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(data => {
      geojsonData = data;
      paivitaLayer();
      if (geojsonLayer && geojsonLayer.getBounds().isValid()) {
        map.fitBounds(geojsonLayer.getBounds(), { padding: [40, 40] });
      }
    })
    .catch(e => console.error("GeoJSON-lataus epäonnistui:", e));
}

init();
