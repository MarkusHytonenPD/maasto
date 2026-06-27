/**
 * Rakennusinventointi — Google Apps Script
 * =========================================
 * Deployaa web-appina:
 *   Suorita nimellä: Minä
 *   Kuka voi käyttää: Kaikki (myös anonyymit)
 *
 * Endpointin URL → docs/config.js:n CONFIG.SHEETS_URL
 *
 * GET  ?tunnus=ky_1001  →  [{tunnus, kommentti, tekija, luokitus, paivamaara, rakennus_nimi}, ...]
 * GET  (ei parametreja) →  kaikki rivit (karttasivun viranomaisteeema lataa kerralla)
 * POST body: JSON text/plain {tunnus, kommentti, tekija, luokitus, rakennus_nimi}  →  {ok: true}
 *
 * HUOM CORS:
 *   GAS-web-appit palauttavat automaattisesti Access-Control-Allow-Origin: *
 *   GET- ja POST-pyynnöille jotka eivät käynnistä preflightiä.
 *   POST on lähetettävä Content-Type: text/plain -otsikolla (ei application/json)
 *   jotta selain ei tee OPTIONS-preflightiä — GAS ei osaa vastata siihen.
 */

// ── Asetukset ──────────────────────────────────────────────────────────────

// Luo tyhjä Google Sheets -taulukko, kopioi sen ID tähän.
// Taulukko-ID löytyy URL:sta: docs.google.com/spreadsheets/d/[ID]/edit
const SPREADSHEET_ID = "KORVAA_TAHAN_SPREADSHEET_ID";

const SHEET_NAME = "Kommentit";
const SARAKKEET  = ["tunnus", "kommentti", "tekija", "luokitus", "paivamaara", "rakennus_nimi"];

// ── Apufunktiot ────────────────────────────────────────────────────────────

/**
 * Palauttaa välilehden. Luo sen otsikkoriveineen jos sitä ei ole.
 */
function getSheet() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(SARAKKEET);
    sheet.getRange(1, 1, 1, SARAKKEET.length)
         .setFontWeight("bold")
         .setBackground("#eeeeee");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/**
 * Muuntaa välilehden tietoalueen objektitaulukoksi.
 * Otsikkorivi toimii avaimina, päivämäärä-objektit muunnetaan merkkijonoksi.
 */
function sheetToObjects(sheet) {
  const data = sheet.getDataRange().getValues();
  if (data.length <= 1) return [];
  const otsikot = data[0];
  return data.slice(1).map(rivi => {
    const obj = {};
    otsikot.forEach((otsikko, i) => {
      const arvo = rivi[i];
      obj[otsikko] = arvo instanceof Date
        ? Utilities.formatDate(arvo, "Europe/Helsinki", "yyyy-MM-dd")
        : arvo;
    });
    return obj;
  });
}

function jsonVastaus(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── GET ────────────────────────────────────────────────────────────────────

/**
 * GET ?tunnus=ky_1001   → rivit tälle tunnukselle
 * GET (ei parametreja)  → kaikki rivit
 */
function doGet(e) {
  try {
    const sheet  = getSheet();
    const kaikki = sheetToObjects(sheet);
    const tunnus = (e.parameter || {}).tunnus;

    const tulos = tunnus
      ? kaikki.filter(r => r.tunnus === tunnus)
      : kaikki;

    return jsonVastaus(tulos);
  } catch (err) {
    return jsonVastaus({ virhe: err.message });
  }
}

// ── POST ───────────────────────────────────────────────────────────────────

/**
 * POST body (Content-Type: text/plain): JSON-merkkijono
 * {tunnus, kommentti, tekija, luokitus, rakennus_nimi}
 * → {ok: true}
 */
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);

    if (!data.tunnus)    return jsonVastaus({ ok: false, virhe: "tunnus puuttuu" });
    if (!data.kommentti) return jsonVastaus({ ok: false, virhe: "kommentti puuttuu" });

    const sheet = getSheet();
    const pvm   = Utilities.formatDate(new Date(), "Europe/Helsinki", "yyyy-MM-dd");

    sheet.appendRow([
      data.tunnus,
      data.kommentti,
      data.tekija       || "",
      data.luokitus     || "",
      pvm,
      data.rakennus_nimi || "",
    ]);

    return jsonVastaus({ ok: true });
  } catch (err) {
    return jsonVastaus({ ok: false, virhe: err.message });
  }
}
