// Kopioi tämä tiedosto nimellä config.js ja täytä arvot.
// config.js ei commitoidu — se on lisätty .gitignore:en.

const CONFIG = {
    // MML Avoin data -rajapinnan API-avain
    // Hankinta: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimet
    MML_API_KEY: "KORVAA_TAHAN_MML_API_AVAIN",

    // Ubigu GeoServer — kaavarasteri WMS
    WMS_URL: "https://ubigu.ubihub.io/geoserver/kaavarasterit/ows",

    // Google Apps Script -endpoint (saadaan deploymentin jälkeen)
    SHEETS_URL: "KORVAA_TAHAN_APPS_SCRIPT_URL",

    // Projektin nimi — vastaa projektit/-kansion nimeä repossa
    PROJEKTI: "heinlansi",

    // GitHub raw -URL repon juureen (GeoJSON-datan haku GitHub Pagesissa)
    GITHUB_RAW: "https://raw.githubusercontent.com/MarkusHytonenPD/maasto/main",
};
