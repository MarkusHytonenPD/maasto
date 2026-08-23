// Kopioi tämä tiedosto nimellä config.js ja täytä arvot.
// HUOM: config.js commitoidaan — GitHub Pages tarjoilee docs/-kansion suoraan
// repostosta, joten ilman tiedostoa julkaistu sivu ei toimisi.
//
// Tässä ovat vain KAIKILLE projekteille yhteiset asetukset. Projektikohtaiset
// asetukset (WMS-tasot, näytettävät sarakkeet, Sheets-ID ja Apps Script -URL)
// ovat repossa tiedostossa projektit/[projekti]/config.json, jonka kartta
// lataa käynnistyksen yhteydessä.

const CONFIG = {
    // MML Avoin data -rajapinnan API-avain.
    // Hankinta: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje
    // Avain on selainsovelluksessa väistämättä julkinen eikä sille voi asettaa
    // verkkotunnusrajausta. Jos avain joutuu väärinkäyttöön: luo uusi
    // OmaTilissä, päivitä tähän, pushaa, poista vanha.
    MML_API_KEY: "KORVAA_TAHAN_MML_API_AVAIN",

    // GitHub raw -URL repon juureen (GeoJSON-datan ja projektin configin haku)
    GITHUB_RAW: "https://raw.githubusercontent.com/MarkusHytonenPD/maasto/main",
};
