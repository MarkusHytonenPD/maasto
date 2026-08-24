/**
 * viranomainen_apps_script.gs
 * ===========================
 * Viranomaisten kommenttien tallennus karttasovelluksesta Google Sheetiin.
 *
 * Yksi rivi per (rakennustunnus, taho): kolme kommentoijatahoa voivat
 * kirjata saman kohteen toisistaan riippumatta, eikä kukaan ylikirjoita
 * toisen kommenttia. Sama tunnus JA sama taho päivittää olemassa olevaa
 * riviä.
 *
 * DEPLOYAUSOHJE:
 * 1. Avaa Sheet Drivesta
 * 2. Laajennukset → Apps Script
 * 3. Kopioi tämä koodi editoriin
 * 4. Tallenna
 * 5. Ota käyttöön → Uusi deployment → Tyyppi: Web-sovellus
 * 6. Suorittaja: Minä, Käyttäjät: Kaikki
 * 7. Ota käyttöön → Kopioi Web app URL
 * 8. Lisää URL projektin config.json:iin avaimella "apps_script_url"
 *
 * Skripti on Sheetiin sidottu (container-bound), joten se löytää taulukon
 * itse — spreadsheet-ID:tä ei tarvitse kopioida mihinkään. Jos deployaat
 * skriptin erillisenä projektina, aseta SPREADSHEET_ID alla.
 *
 * HUOM CORS:
 *   Apps Script -web-appien vastauksissa on Access-Control-Allow-Origin: *
 *   niille pyynnöille jotka eivät laukaise preflightiä. POST on siksi
 *   lähetettävä Content-Type: text/plain -otsikolla (ei application/json):
 *   Apps Script ei osaa vastata OPTIONS-preflightiin.
 *
 * Rajapinta:
 *   GET   (ilman parametreja)  → {status:"ok", rivit:[{tunnus, taho, luokitus_vir, ...}]}
 *   GET   ?tunnus=63           → {status:"ok", rivit:[...]}  (vain tämä tunnus)
 *   POST  body JSON text/plain {tunnus, taho, luokitus_vir, kommentti_vir, nimi_vir}
 *                              → {status:"ok", toiminto:"paivitetty"|"lisatty"}
 *   Virhe → {status:"error", message:"..."}
 */

// ── Asetukset ──────────────────────────────────────────────────────────────

// Jätä tyhjäksi kun skripti on Sheetiin sidottu (normaali tapaus).
const SPREADSHEET_ID = "";

// Välilehden nimi — sama kuin pipeline.py:n SHEET_VALILEHTI.
const SHEET_NAME = "Lausunnot";

// Otsikkorivin sarakkeet — sama järjestys kuin pipeline.py:n SHEET_OTSIKOT.
const SARAKKEET = ["tunnus", "taho", "luokitus_vir", "kommentti_vir", "nimi_vir"];

// Sallitut tahot. Sama lista kuin kartta.js:n TAHOT — tuntematon taho
// hylätään, jottei kirjoitusvirhe synnytä näkymätöntä neljättä kommenttia.
const TAHOT = ["LVV", "Vastuumuseo", "Maakuntaliitto"];

// ── Apufunktiot ────────────────────────────────────────────────────────────

function getSheet() {
  const ss = SPREADSHEET_ID
    ? SpreadsheetApp.openById(SPREADSHEET_ID)
    : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error("Taulukkoa ei löydy — aseta SPREADSHEET_ID.");
  }
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(SARAKKEET);
    sheet.setFrozenRows(1);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(SARAKKEET);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/**
 * Otsikkorivi → {sarakenimi: 0-pohjainen indeksi}. Näin sarakkeiden
 * järjestys tai ylimääräiset sarakkeet eivät riko skriptiä.
 */
function sarakeIndeksit(sheet) {
  const otsikot = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const indeksit = {};
  otsikot.forEach(function (nimi, i) {
    indeksit[String(nimi).trim()] = i;
  });
  // Puuttuvat sarakkeet lisätään otsikkoriviin loppuun
  SARAKKEET.forEach(function (nimi) {
    if (!(nimi in indeksit)) {
      const uusi = sheet.getLastColumn() + 1;
      sheet.getRange(1, uusi).setValue(nimi);
      indeksit[nimi] = uusi - 1;
    }
  });
  return indeksit;
}

function vastaus(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function virhe(viesti) {
  return vastaus({ status: "error", message: String(viesti) });
}

function lueRivit(sheet, idx) {
  if (sheet.getLastRow() < 2) return [];
  const data = sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).getValues();
  return data
    .filter(function (rivi) { return String(rivi[idx.tunnus]).trim() !== ""; })
    .map(function (rivi) {
      const o = {};
      SARAKKEET.forEach(function (nimi) {
        const arvo = rivi[idx[nimi]];
        o[nimi] = arvo === null || arvo === undefined ? "" : String(arvo);
      });
      return o;
    });
}

// ── GET ────────────────────────────────────────────────────────────────────

function doGet(e) {
  try {
    const sheet = getSheet();
    const idx   = sarakeIndeksit(sheet);
    let rivit   = lueRivit(sheet, idx);

    const tunnus = e && e.parameter && e.parameter.tunnus;
    if (tunnus) {
      const haettu = String(tunnus).trim();
      rivit = rivit.filter(function (r) { return r.tunnus === haettu; });
    }
    return vastaus({ status: "ok", rivit: rivit });
  } catch (err) {
    return virhe(err);
  }
}

// ── POST ───────────────────────────────────────────────────────────────────

function doPost(e) {
  const lukko = LockService.getScriptLock();
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return virhe("Pyynnöstä puuttuu body.");
    }

    let data;
    try {
      data = JSON.parse(e.postData.contents);
    } catch (parseErr) {
      return virhe("Body ei ole kelvollista JSONia.");
    }

    const tunnus = data.tunnus === null || data.tunnus === undefined
      ? "" : String(data.tunnus).trim();
    if (!tunnus) {
      return virhe("Kentta 'tunnus' puuttuu.");
    }

    const taho = data.taho === null || data.taho === undefined
      ? "" : String(data.taho).trim();
    if (!taho) {
      return virhe("Kentta 'taho' puuttuu.");
    }
    if (TAHOT.indexOf(taho) === -1) {
      return virhe("Tuntematon taho: " + taho + ". Sallitut: " + TAHOT.join(", "));
    }

    // Estää päällekkäisten tallennusten sekoittumisen
    if (!lukko.tryLock(20000)) {
      return virhe("Taulukko on varattu — yritä hetken kuluttua uudelleen.");
    }

    const sheet = getSheet();
    const idx   = sarakeIndeksit(sheet);
    const leveys = sheet.getLastColumn();

    // Etsitään rivi jossa sekä tunnus että taho täsmää
    let kohderivi = 0;
    if (sheet.getLastRow() >= 2) {
      const rivit = sheet
        .getRange(2, 1, sheet.getLastRow() - 1, leveys)
        .getValues();
      for (let i = 0; i < rivit.length; i++) {
        if (String(rivit[i][idx.tunnus]).trim() === tunnus &&
            String(rivit[i][idx.taho]).trim() === taho) {
          kohderivi = i + 2;   // +2: otsikkorivi ja 1-pohjainen indeksointi
          break;
        }
      }
    }

    const paivitetty = kohderivi > 0;
    const rivi = paivitetty
      ? sheet.getRange(kohderivi, 1, 1, leveys).getValues()[0]
      : new Array(leveys).fill("");

    rivi[idx.tunnus] = tunnus;
    rivi[idx.taho]   = taho;
    ["luokitus_vir", "kommentti_vir", "nimi_vir"].forEach(function (nimi) {
      if (nimi in data) {
        const arvo = data[nimi];
        rivi[idx[nimi]] = arvo === null || arvo === undefined ? "" : String(arvo);
      }
    });

    const rivinumero = paivitetty ? kohderivi : sheet.getLastRow() + 1;
    sheet.getRange(rivinumero, 1, 1, leveys).setValues([rivi]);
    SpreadsheetApp.flush();

    return vastaus({
      status:   "ok",
      toiminto: paivitetty ? "paivitetty" : "lisatty",
      tunnus:   tunnus,
      taho:     taho,
    });
  } catch (err) {
    return virhe(err);
  } finally {
    try { lukko.releaseLock(); } catch (ignore) {}
  }
}
