# Keys that map directly to Textual Theme fields.
# "key" is a custom extra that overrides footer-key-foreground via Theme.variables.
THEME_FIELDS: frozenset[str] = frozenset(
    {"primary", "secondary", "background", "surface", "panel", "boost"}
)

# Colors extracted from each station's production CSS bundle.
# primary    = dominant brand accent (tabs, borders, focus ring)
# secondary  = highlight/hover variant of primary
# background = darkest app chrome
# surface    = list rows, card backgrounds
# panel      = sidebar / info panel backgrounds
# boost      = selected / hover lift
# key        = (optional) footer hotkey letter color; overrides footer-key-foreground
STATION_PALETTES: dict[str, dict[str, str]] = {
    "di": {
        "primary":    "#288cfb",
        "secondary":  "#09d3b7",
        "background": "#181f2d",
        "surface":    "#262e41",
        "panel":      "#2B5AA4",
        "boost":      "#3c455f",
        "key":        "#0a1525",
    },
    "radiotunes": {
        "primary":    "#eb8700",
        "secondary":  "#ffa224",
        "background": "#091e30",
        "surface":    "#0c2031",
        "panel":      "#0e3860",
        "boost":      "#1671be",
    },
    "rockradio": {
        "primary":    "#f9dc00",
        "secondary":  "#d6b802",
        "background": "#161616",
        "surface":    "#2e2e2e",
        "panel":      "#3b3b3b",
        "boost":      "#4b4b4b",
    },
    "jazzradio": {
        "primary":    "#e8a548",
        "secondary":  "#feb95b",
        "background": "#2f2121",
        "surface":    "#401417",
        "panel":      "#4d272a",
        "boost":      "#70494c",
    },
    "classicalradio": {
        "primary":    "#3ac6a1",
        "secondary":  "#42dab4",
        "background": "#002433",
        "surface":    "#033043",
        "panel":      "#043a52",
        "boost":      "#173445",
    },
    "zenradio": {
        "primary":    "#15afa7",
        "secondary":  "#1addd2",
        "background": "#052c30",
        "surface":    "#073e43",
        "panel":      "#094449",
        "boost":      "#146870",
    },
}
