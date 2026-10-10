"""Prototyp animace mapy: kamera sleduje velikost útvaru (říše = oddálení, ČSR/ČR = přiblížení).

Výstup: assets/mapy/mapa_animace.gif
Použití: python3 src/mapa_animace.py
"""
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MPath
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
FPS = 20
DRZET, PRECHOD = 0.9, 1.1  # sekundy: setrvání na období, přechod mezi obdobími
SIRKA, VYSKA = 7.2, 4.8  # palce -> 720×480 px při dpi 100 (poměr 3:2)
KX = math.cos(math.radians(49))  # jednoduchá projekce: zúžení zeměpisné délky

STYL = dict(more="#0d1b2a", pevnina="#1f2a36", hranice="#3b4a5a", utvar="#f2b33d", ztrata="#7a8796",
            cr="#ffffff", text="#e8edf2", text2="#8fa3b8")

OBDOBI = [  # (soubor, popisek roku, název útvaru)
    ("1754", "1754", "Habsburská monarchie"),
    ("1850_1857", "1850", "Rakouské císařství"),
    ("1869", "1869", "Rakousko-Uhersko"),
    ("1910_1914", "1910", "Rakousko-Uhersko"),
    ("1918_1920", "1918", "Československo"),
    ("1921_1930", "1930", "Československo"),
    ("1938", "1938", "Československo"),
    ("1945_1950", "1945", "Československo"),
    ("1961_1991", "1961", "ČSSR"),
    ("1993_2021", "1993", "Česká republika"),
]


def nacti(obdobi):
    fc = json.loads((ROOT / "data" / "mapy" / f"{obdobi}.geojson").read_text())
    role = {"utvar": [], "cr": [], "okoli": []}
    for ft in fc["features"]:
        role[ft["properties"]["role"]].append(shape(ft["geometry"]))
    return unary_union(role["utvar"]), role["cr"][0], role["okoli"]


def kamera(geom, okraj=0.12):
    """Výřez (střed x, střed y, šířka) v projekci, který útvar celý ukáže v poměru 3:2."""
    x0, y0, x1, y1 = geom.bounds
    w, h = (x1 - x0) * KX, (y1 - y0)
    w = max(w, h * SIRKA / VYSKA) * (1 + 2 * okraj)
    return ((x0 + x1) / 2 * KX, (y0 + y1) / 2, w)


def ease(t):
    return t * t * (3 - 2 * t)


def kresli(ax, geom, **kw):
    """Vykreslí (multi)polygon včetně děr jako jednu složenou cestu."""
    vrcholy, kody = [], []
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        for ring in (p.exterior, *p.interiors):
            xy = [(x * KX, y) for x, y in ring.coords]
            vrcholy += xy
            kody += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY]
    if vrcholy:
        ax.add_patch(PathPatch(MPath(vrcholy, kody), joinstyle="round", capstyle="round", **kw))


data = [nacti(o) for o, _, _ in OBDOBI]
kamery = [kamera(u) for u, _, _ in data]
cr = data[0][1]
n_drz, n_pre = int(DRZET * FPS), int(PRECHOD * FPS)
plan = []  # (index období, t přechodu do dalšího)
for i in range(len(OBDOBI)):
    plan += [(i, 0.0)] * n_drz
    if i < len(OBDOBI) - 1:
        plan += [(i, (k + 1) / n_pre) for k in range(n_pre)]
plan += [(len(OBDOBI) - 1, 0.0)] * FPS  # delší závěr

fig = plt.figure(figsize=(SIRKA, VYSKA), dpi=100)
ax = fig.add_axes([0, 0, 1, 1])


def snimek(f):
    i, t = plan[f]
    j = min(i + 1, len(OBDOBI) - 1)
    te = ease(t)
    ax.clear()
    ax.set_facecolor(STYL["more"])
    ax.set_xticks([]); ax.set_yticks([])

    # kamera: střed lineárně, šířka geometricky (plynulý zoom)
    (cx0, cy0, w0), (cx1, cy1, w1) = kamery[i], kamery[j]
    cx, cy = cx0 + (cx1 - cx0) * te, cy0 + (cy1 - cy0) * te
    w = math.exp(math.log(w0) + (math.log(w1) - math.log(w0)) * te)
    h = w * VYSKA / SIRKA
    ax.set_xlim(cx - w / 2, cx + w / 2); ax.set_ylim(cy - h / 2, cy + h / 2)

    # podklad: pevnina pod oběma útvary, aby prolínání nemělo pod sebou místy moře
    kresli(ax, data[i][0].union(data[j][0]), fc=STYL["pevnina"], ec="none", zorder=0.5)
    # pevnina a hranice okolí (prolnutí mezi obdobími)
    for k, a in ((i, 1 - te), (j, te)):
        if a <= 0.01:
            continue
        for g in data[k][2]:
            kresli(ax, g, fc=STYL["pevnina"], ec=STYL["hranice"], lw=0.6, alpha=a, zorder=1)

    # útvar: společná část pevně, ztracené území šedne, nové se objevuje
    u0, u1 = data[i][0], data[j][0]
    if i == j or t == 0:
        kresli(ax, u0, fc=STYL["utvar"], ec="none", zorder=2)
        obrys = u0
    else:
        kresli(ax, u0.intersection(u1), fc=STYL["utvar"], ec="none", zorder=2)
        kresli(ax, u0.difference(u1), fc=STYL["utvar"], ec="none", alpha=1 - te, zorder=2)
        kresli(ax, u0.difference(u1), fc=STYL["ztrata"], ec="none", alpha=te * 0.35, zorder=2)
        kresli(ax, u1.difference(u0), fc=STYL["utvar"], ec="none", alpha=te, zorder=2)
        obrys = u1 if te > 0.5 else u0
    # záře okraje útvaru
    for lw, a in ((7, 0.06), (4, 0.12), (1.2, 0.9)):
        kresli(ax, obrys, fill=False, ec=STYL["utvar"], lw=lw, alpha=a, zorder=3)

    # obrys dnešní ČR se září
    for lw, a in ((6, 0.08), (3, 0.18), (1.3, 0.95)):
        kresli(ax, cr, fill=False, ec=STYL["cr"], lw=lw, alpha=a, zorder=4)

    # Praha
    ax.plot(14.42 * KX, 50.08, "o", ms=4, color=STYL["cr"], zorder=5)

    # popisky: rok a útvar (během přechodu se přepnou v polovině)
    k = j if te > 0.5 else i
    ax.text(0.04, 0.12, OBDOBI[k][1], transform=ax.transAxes, fontsize=34, weight="bold", color=STYL["text"], zorder=6)
    ax.text(0.04, 0.05, OBDOBI[k][2], transform=ax.transAxes, fontsize=15, color=STYL["utvar"], zorder=6)
    ax.text(0.96, 0.04, "obrys = dnešní Česko", transform=ax.transAxes, fontsize=9, color=STYL["text2"], ha="right", zorder=6)


anim = FuncAnimation(fig, snimek, frames=len(plan))
anim.save(ROOT / "assets" / "mapy" / "mapa_animace.gif", writer=PillowWriter(fps=FPS))
snimek(plan.index((6, 0.0)) + 2)  # statický náhled roku 1938
fig.savefig(ROOT / "assets" / "mapy" / "mapa_styl_1938.png")
print("snímků:", len(plan), "délka:", round(len(plan) / FPS, 1), "s")
