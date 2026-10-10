"""Připraví mapy hranic pro jednotlivá období.

Pro každé období uloží do data/mapy/<obdobi>.geojson:
  - role="utvar": státní útvar, k němuž patřilo dnešní území ČR,
  - role="cr":    obrys dnešní ČR (konstantní, na tomto území jsou data ČSÚ),
  - role="okoli": ostatní státy oříznuté na výřez (jen šedé pozadí).

Zdroje:
  - OpenHistoricalMap (CC0) — útvary od roku 1852 a obrys ČR, hranice přesně po datech,
  - Historical Basemaps, github.com/aourednik/historical-basemaps (GPL-3.0)
    — habsburská monarchie 1754–1800 (OHM ji pro 18. století nemá) a šedé okolí.

Stažené soubory se ukládají do mezipaměti mimo Google Drive (~/.cache/cesko_v_cislech).

Použití: python3 src/mapy.py
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "mapy"
CACHE = Path.home() / ".cache" / "cesko_v_cislech"
UA = {"User-Agent": "CeskoVCislech/0.1 (portfolio project)"}
PRAHA = Point(14.42, 50.08)
VYREZ = box(-20, 28, 58, 66)  # oříznutí okolí (s rezervou i pro oddálený záběr na celou monarchii)

# období -> (zdroj útvaru, mapa Historical Basemaps pro okolí)
# zdroj útvaru: ("hb", rok) nebo ("ohm", id relace, název, platnost)
OBDOBI = {
    "1754": (("hb", "1783", [("1715", "Polish–Lithuanian Commonwealth")]), "1783"),  # bez Haliče a Bukoviny
    "1772_1800": (("hb", "1783"), "1783"),
    "1800": (("hb", "1800"), "1800"),
    "1850_1857": (("ohm", 2746346, "Austrian Empire", "1852–1859"), "1815"),
    "1869": (("ohm", 2692702, "Austria-Hungary", "1867–1878"), "1880"),
    "1880_1900": (("ohm", 2746402, "Austria-Hungary", "1878–1908"), "1900"),
    "1910_1914": (("ohm", 2692361, "Austria-Hungary", "1908–1918"), "1914"),
    "1918_1920": (("ohm", 2747877, "Czechoslovakia", "1918–1920"), "1920"),
    "1921_1930": (("ohm", 2692233, "Czechoslovakia", "1924–1936"), "1930"),
    "1938": (("ohm", 2857482, "Czechoslovakia", "2. 11. 1938 – 14. 3. 1939"), "1938"),
    "1939_1945": (("ohm", 2704750, "Protectorate of Bohemia and Moravia", "14. 3. 1939 – 8. 5. 1945"), "1938"),
    "1945_1950": (("ohm", 2692234, "Czechoslovakia", "1948–1960"), "1945"),
    "1961_1991": (("ohm", 2830315, "Czechoslovak Socialist Republic", "1960–1990"), "1960"),
    "1993_2021": (("ohm", 2692745, "Czech Republic", "od 1993"), "2010"),
}
CR_OHM = 2692745


def stahni(url, soubor, data=None):
    cesta = CACHE / soubor
    if not cesta.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, data=data, headers=UA)
        cesta.write_bytes(urllib.request.urlopen(req, timeout=300).read())
        time.sleep(2)  # šetrně k Overpass API
    return json.loads(cesta.read_text())


def hb(rok):
    url = f"https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_{rok}.geojson"
    return stahni(url, f"world_{rok}.geojson")["features"]


def ohm(relace):
    dotaz = f"[out:json][timeout:250];relation({relace});out geom;"
    data = urllib.parse.urlencode({"data": dotaz}).encode()
    e = stahni("https://overpass-api.openhistoricalmap.org/api/interpreter", f"ohm_{relace}.json", data)["elements"][0]
    cary = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
            for m in e["members"] if m["type"] == "way" and m.get("role") in ("outer", "") and m.get("geometry")]
    return unary_union(list(polygonize(unary_union(cary)))).buffer(0)


def najdi(features, bod):
    for ft in features:
        if ft["geometry"] and shape(ft["geometry"]).contains(bod):
            return ft


def zjednodus(geom, tol):
    """Zjednoduší geometrii pro video (tol ve stupních; 0.002° ≈ 150 m, na výstupu neviditelné)."""
    return geom.simplify(tol, preserve_topology=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cr = zjednodus(ohm(CR_OHM), 0.002)
    for obdobi, (zdroj, okoli_rok) in OBDOBI.items():
        okoli = hb(okoli_rok)
        if zdroj[0] == "hb":
            # Celé dnešní území ČR patřilo habsburské monarchii (kromě drobného Hlučínska, pruského 1742–1920);
            # sjednocení s obrysem ČR z OHM zarovná okraje na hranici ČR.
            geom = shape(najdi(hb(zdroj[1]), PRAHA)["geometry"]).buffer(0)
            for rok_odectu, nazev in (zdroj[2] if len(zdroj) > 2 else []):
                # území, které Habsburkům tehdy ještě nepatřilo (podle staršího stavu mapy)
                geom = geom.difference(unary_union([shape(f["geometry"]).buffer(0) for f in hb(rok_odectu)
                                                    if f["geometry"] and f["properties"].get("NAME") == nazev]))
            geom = unary_union([geom, cr])
            popis = {"zdroj": f"Historical Basemaps world_{zdroj[1]}", "name": "Habsburg Monarchy"}
        else:
            geom = zjednodus(ohm(zdroj[1]), 0.002)
            popis = {"zdroj": f"OpenHistoricalMap relace {zdroj[1]} ({zdroj[3]})", "name": zdroj[2]}
        out = [
            {"type": "Feature", "properties": {"role": "utvar", **popis}, "geometry": mapping(geom)},
            {"type": "Feature", "properties": {"role": "cr", "name": "Czech Republic"}, "geometry": mapping(cr)},
        ]
        for ft in okoli:
            if not ft["geometry"]:
                continue
            g = zjednodus(shape(ft["geometry"]).buffer(0).intersection(VYREZ), 0.01).difference(geom)
            if not g.is_empty and g.area > 1e-4:
                out.append({"type": "Feature", "properties": {"role": "okoli", "name": ft["properties"].get("NAME")},
                            "geometry": mapping(g)})
        (OUT / f"{obdobi}.geojson").write_text(json.dumps({"type": "FeatureCollection", "zdroj": popis["zdroj"], "features": out}))
        print(obdobi, "-", popis["zdroj"])


if __name__ == "__main__":
    main()
