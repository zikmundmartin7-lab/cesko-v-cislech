"""Náhled připravených map (data/mapy/*.geojson) v bližším výřezu kolem ČR."""
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
VYREZ = (11.3, 25.3, 46.9, 52.0)  # lon_min, lon_max, lat_min, lat_max
BARVY = {"utvar": dict(fc="#f2c14e", ec="#b8860b", lw=0.8, zorder=2),
         "okoli": dict(fc="#e6e6e6", ec="#999", lw=0.5, zorder=1),
         "cr": dict(fill=False, ec="#c0392b", lw=2.2, zorder=3)}
POPISKY = {"1754": "1754: Habsburská monarchie", "1772_1800": "1772–1800: Habsburská monarchie",
           "1850_1857": "1850–1857: Rakouské císařství", "1869": "1869: Rakousko-Uhersko",
           "1880_1900": "1880–1900: Rakousko-Uhersko", "1910_1914": "1910–1914: Rakousko-Uhersko",
           "1918_1920": "1918–1920: Československo", "1921_1930": "1921–1930: Československo",
           "1938": "1938: Československo po Mnichovu", "1945_1950": "1945–1950: Československo",
           "1961_1991": "1961–1991: ČSSR / ČSFR", "1993_2021": "1993–2021: Česká republika"}


def kresli(ax, geom, **kw):
    for p in getattr(geom, "geoms", [geom]):
        ax.add_patch(Polygon(list(p.exterior.coords), closed=True, **kw))


fig, axs = plt.subplots(4, 4, figsize=(20, 12))
for ax, (obdobi, popis) in zip(axs.flat, POPISKY.items()):
    fc = json.loads((ROOT / "data" / "mapy" / f"{obdobi}.geojson").read_text())
    for ft in sorted(fc["features"], key=lambda f: f["properties"]["role"] == "cr"):
        kresli(ax, shape(ft["geometry"]), **BARVY[ft["properties"]["role"]])
    ax.set_xlim(*VYREZ[:2]); ax.set_ylim(*VYREZ[2:])
    ax.set_aspect(1 / math.cos(math.radians(50)))
    ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#cfe3f3")
    ax.set_title(f"{popis}\n{fc['zdroj']}", fontsize=10)
for ax in list(axs.flat)[len(POPISKY):]:
    ax.axis("off")
axs.flat[len(POPISKY)].text(0.02, 0.5, "žlutě = státní útvar\nčerveně = dnešní ČR (území dat ČSÚ)\n\nútvary od 1852 a obrys ČR: OpenHistoricalMap (CC0)\n1754–1800 a šedé okolí: Historical Basemaps (GPL-3.0)", fontsize=11, va="center")
fig.tight_layout()
fig.savefig(ROOT / "assets" / "mapy" / "nahled_map_blizko.png", dpi=80)
