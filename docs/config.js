const CONFIG = {
    MML_API_KEY: "8ed41c4f-ff68-42a3-ae7a-970474a60cd3",
    SHEETS_URL:  "",
    PROJEKTI:    "hein_ita_demo",
    GITHUB_RAW:  "https://raw.githubusercontent.com/MarkusHytonenPD/maasto/main",

    // WMS-tasot layer controliin. nakyva: false → piilotettu oletuksena.
    TASOT: [
        {
            nimi:   "Kaavaluonnos",
            url:    "https://ubigu.ubihub.io/geoserver/kaavarasterit/ows",
            layer:  "kaavarasterit:hein_lans_luonnos",
            nakyva: true,
        },
    ],
};
