// Kopioi tämä tiedosto nimellä config.js ja täytä arvot.
// config.js ei commitoidu — se on lisätty .gitignore:en.

const CONFIG = {
    // MML Avoin data -rajapinnan API-avain
    // Hankinta: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimet
    MML_API_KEY: "KORVAA_TAHAN_MML_API_AVAIN",

    // Google Apps Script -endpoint (saadaan deploymentin jälkeen)
    SHEETS_URL: "KORVAA_TAHAN_APPS_SCRIPT_URL",

    // Projektin nimi — vastaa projektit/-kansion nimeä repossa
    PROJEKTI: "heinlansi",

    // GitHub raw -URL repon juureen (GeoJSON-datan haku GitHub Pagesissa)
    GITHUB_RAW: "https://raw.githubusercontent.com/MarkusHytonenPD/maasto/main",

    // WMS-tasot layer controliin. nakyva: false → piilotettu oletuksena.
    TASOT: [
        {
            nimi:   "Kaavaluonnos",
            url:    "https://ubigu.ubihub.io/geoserver/kaavarasterit/ows",
            layer:  "kaavarasterit:KORVAA_LAYER_NIMI",
            nakyva: true,
        },
        // Lisää tarpeen mukaan:
        // {
        //     nimi:   "Toinen taso",
        //     url:    "https://...",
        //     layer:  "workspace:layername",
        //     nakyva: false,
        // },
    ],
};
