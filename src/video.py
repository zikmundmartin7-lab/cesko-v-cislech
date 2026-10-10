"""Česko v číslech — render videa (svislé 1080×1920, MP4).

Struktura a čísla: data/timeline.csv, mapy: data/mapy/*.geojson, vlajky: assets/vlajky/*.png,
texty: texty/<jazyk>.json (jediné místo, které se liší mezi jazykovými verzemi).

Použití:
    python3 src/video.py                  # čeština, plné rozlišení
    python3 src/video.py --jazyk en
    python3 src/video.py --nahled         # poloviční rozlišení a fps pro rychlou kontrolu
"""
import argparse
import json
import math
import textwrap
from pathlib import Path

import imageio_ffmpeg
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.animation import FFMpegWriter
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, PathPatch, Polygon, Rectangle
from matplotlib.path import Path as MPath
from PIL import Image
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
W, H = 1080, 1920
FONT = "Avenir Next"

BARVY = dict(
    pozadi="#0d1b2a", pevnina="#1f2a36", hranice="#3b4a5a", utvar="#f2b33d", ztrata="#7a8796",
    cr="#ffffff", text="#e8edf2", text2="#8fa3b8", mrizka="#22303f",
    muzi="#3987e5", zeny="#d95926", odhad="#8fa3b8",  # muži/ženy: sloty 1 a 2 validované palety (tmavý režim)
    okupace="#8c8273",  # protektorát: území ukázané, ale tlumeně (nešlo o samostatný stát)
    nahoru="#0ca30c", dolu="#d03b3b",  # stavové barvy: vždy spolu s tvarem šipky
)

# Hranice období podle roku (útvar, vlajka, mapa). Změna nastává, když letopočet hranici překročí.
UTVARY = [(-1e9, "hm"), (1804, "rc"), (1867, "ru"), (1918, "csr"), (1939, "prot"), (1945, "csr"),
          (1960, "cssr"), (1990, "csfr"), (1993, "cr")]
VLAJKY = [(-1e9, "habsburska"), (1804, "rak_cis"), (1867, "ru"), (1918, "bila_cervena"), (1920.2, "cs"),
          (1939, "zadna"), (1945, "cs")]
MAPY = [(-1e9, "1754"), (1772, "1772_1800"), (1820, "1850_1857"), (1867, "1869"), (1878, "1880_1900"), (1908, "1910_1914"),
        (1918, "1918_1920"), (1921, "1921_1930"), (1938, "1938"), (1939, "1939_1945"), (1945, "1945_1950"),
        (1960.5, "1961_1991"), (1993, "1993_2021")]

# Časování (sekundy videa)
HOOK, PULLBACK, ZAVER = 3.2, 0.8, 6.0  # PULLBACK = náběh mapy před první událostí; ZAVER = pointa 1930 vs. 2021
TICHE = {1914, 1939, 1950}
OKUPACE = {"1939_1945"}  # období, kdy území nebylo samostatným státem (tlumená barva na mapě)  # válečné momenty: tlumená ikona, delší čas
TEMPO = 1.25  # násobek délky všech událostí (1 = původní tempo ~75 s videa)


def trvani(rok, typ):
    if rok in TICHE:
        zaklad = 3.2
    elif typ == "udalost":
        zaklad = 2.4
    elif rok < 1857:
        zaklad = 1.8
    elif rok == 2021:
        zaklad = 2.6
    else:
        zaklad = 2.1
    return zaklad * TEMPO


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease_back(t, c=1.7):
    """Náběh s mírným přestřelením (0 -> ~1.1 -> 1)."""
    t = min(max(t, 0.0), 1.0) - 1
    return 1 + (c + 1) * t ** 3 + c * t ** 2


def obdelnik(x, y, sirka, vyska):
    """Pozice osy z pixelů (x zleva, y od horního okraje) do souřadnic obrázku."""
    return [x / W, 1 - (y + vyska) / H, sirka / W, vyska / H]


# ---------------------------------------------------------------- data a časová osa
class Osa:
    def __init__(self, fps):
        t = pd.read_csv(ROOT / "data" / "timeline.csv", keep_default_na=False)
        self.radky = list(t.itertuples(index=False))
        self.fps = fps
        self.start = []  # čas začátku každého řádku
        cas = HOOK + PULLBACK
        for r in self.radky:
            self.start.append(cas)
            cas += trvani(r.rok, r.typ)
        self.konec_dat = cas
        self.delka = cas + ZAVER
        self.n = int(self.delka * fps)
        self.roky = np.array([r.rok for r in self.radky], float)
        # datové body
        d = [r for r in self.radky if r.typ != "udalost"]
        self.d_rok = np.array([r.rok for r in d], float)
        self.d_cel = np.array([float(r.celkem) for r in d])
        # řada pro počítadlo: sčítání a odhady + ve válečných obdobích roční střední stavy (umístěné na rok + 0,5),
        # aby počítadlo mezi sčítáními ukazovalo skutečný průběh, ne jen přímku (viz src/rocni_odhady.py)
        ro = pd.read_csv(ROOT / "data" / "rocni_odhady.csv")
        x = np.concatenate([self.d_rok, ro.rok.to_numpy(float) + 0.5])
        v = np.concatenate([self.d_cel, ro.stredni_stav.to_numpy(float)])
        o = np.argsort(x)
        self.p_rok, self.p_cel = x[o], v[o]

    def pocet(self, rok):
        return float(np.interp(rok, self.p_rok, self.p_cel))

    def rok(self, cas):
        """Plynulý letopočet: v rámci řádku se posouvá k dalšímu řádku, u každého bodu zpomalí."""
        if cas < HOOK + PULLBACK:
            return self.roky[0]
        i = max(k for k, s in enumerate(self.start) if s <= cas) if cas >= self.start[0] else 0
        if i == len(self.radky) - 1:
            return self.roky[-1]
        p = (cas - self.start[i]) / trvani(self.radky[i].rok, self.radky[i].typ)
        f = ease((p - 0.45) / 0.55)  # první polovinu řádku letopočet drží rok události, pak se rozběhne
        return self.roky[i] + (self.roky[i + 1] - self.roky[i]) * f

    def radek(self, cas):
        if cas < self.start[0]:
            return None
        return max(k for k, s in enumerate(self.start) if s <= cas)

    def cas_roku(self, rok):
        """První čas videa, kdy letopočet dosáhne daného roku."""
        if not hasattr(self, "_roky_snimku"):
            self._roky_snimku = np.array([self.rok(k / self.fps) for k in range(self.n)])
            self._roky_snimku[: int((HOOK + PULLBACK) * self.fps)] = -1e9
        k = np.argmax(self._roky_snimku >= rok)
        return k / self.fps if self._roky_snimku[k] >= rok else self.delka


def stav_v_case(hranice, osa, cas, pocatek=None):
    """Vrátí (předchozí klíč, aktuální klíč, čas přechodu) pro období řízená letopočtem."""
    udalosti = [] if pocatek is None else [pocatek]
    for i, (rok, klic) in enumerate(hranice):
        udalosti.append((HOOK if i == 0 else osa.cas_roku(rok), klic))
    return udalosti


def aktualni(udalosti, cas):
    k = max([i for i, (t, _) in enumerate(udalosti) if t <= cas] or [0])
    pred = udalosti[k - 1][1] if k > 0 else udalosti[0][1]
    return pred, udalosti[k][1], udalosti[k][0]


# ---------------------------------------------------------------- mapa
def cesta(geom, kx):
    vrcholy, kody = [], []
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        for ring in (p.exterior, *p.interiors):
            xy = [(x * kx, y) for x, y in ring.coords]
            vrcholy += xy
            kody += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY]
    return MPath(vrcholy, kody) if vrcholy else None


class Mapa:
    KX = math.cos(math.radians(49))

    def __init__(self, ax, poradi, cista=(0.0, 1.0)):
        self.ax = ax
        self.cista = cista  # svislý rozsah panelu (zdola, 0..1), kde mapu nic nepřekrývá
        bbox = ax.get_position()
        self.pomer = (bbox.width * W) / (bbox.height * H)
        self.geo = {}
        for klic in set(poradi):
            fc = json.loads((ROOT / "data" / "mapy" / f"{klic}.geojson").read_text())
            role = {"utvar": [], "cr": [], "okoli": []}
            for ft in fc["features"]:
                role[ft["properties"]["role"]].append(shape(ft["geometry"]))
            self.geo[klic] = (unary_union(role["utvar"]), role["cr"][0], unary_union(role["okoli"]))
        # záběr vždy pokryje útvar i obrys dnešního Česka (ten je větší např. u protektorátu nebo v roce 1938)
        self.kamera = {k: self._kamera(g[0].union(g[1])) for k, g in self.geo.items()}
        barva = {k: BARVY["okupace"] if k in OKUPACE else BARVY["utvar"] for k in self.geo}
        cr = self.geo["1993_2021"][1]

        ax.set_facecolor(BARVY["pozadi"])
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        pevnina = unary_union([g[2] for g in self.geo.values()] + [g[0] for g in self.geo.values()])
        self._patch(pevnina, fc=BARVY["pevnina"], ec="none", zorder=0.5)
        self.hranice = {k: self._patch(g[2], fill=False, ec=BARVY["hranice"], lw=0.8, zorder=1) for k, g in self.geo.items()}
        self.vypln = {k: self._patch(g[0], fc=barva[k], ec="none", zorder=2) for k, g in self.geo.items()}
        self.zare = {k: [self._patch(g[0], fill=False, ec=barva[k], lw=lw, zorder=3) for lw in (10, 5, 1.8)]
                     for k, g in self.geo.items()}
        self.prechody = {}
        for a, b in zip(poradi, poradi[1:]):
            ua, ub = self.geo[a][0], self.geo[b][0]
            if a in OKUPACE or b in OKUPACE:  # změna barvy: celé útvary se prolnou
                self.prechody[(a, b)] = dict(stary=self._patch(ua, fc=barva[a], ec="none", zorder=2),
                                             novy=self._patch(ub, fc=barva[b], ec="none", zorder=2.1))
                continue
            self.prechody[(a, b)] = dict(
                spolecne=self._patch(ua.intersection(ub), fc=BARVY["utvar"], ec="none", zorder=2),
                ztrata=self._patch(ua.difference(ub), fc=BARVY["utvar"], ec="none", zorder=2),
                ztrata_seda=self._patch(ua.difference(ub), fc=BARVY["ztrata"], ec="none", zorder=2),
                nove=self._patch(ub.difference(ua), fc=BARVY["utvar"], ec="none", zorder=2),
            )
        self.cr = [self._patch(cr, fill=False, ec=BARVY["cr"], lw=lw, alpha=a, zorder=4)
                   for lw, a in ((9, 0.08), (4.5, 0.18), (2, 0.95))]
        self.praha, = ax.plot(14.42 * self.KX, 50.08, "o", ms=7, color=BARVY["cr"], zorder=5)
        self.vse = [p for p in [*self.hranice.values(), *self.vypln.values(),
                                *[z for zz in self.zare.values() for z in zz],
                                *[p for d in self.prechody.values() for p in d.values()]] if p is not None]

    def _patch(self, geom, **kw):
        if geom is None or geom.is_empty:
            return None
        c = cesta(geom, self.KX)
        if c is None:
            return None
        p = PathPatch(c, joinstyle="round", capstyle="round", **kw)
        self.ax.add_patch(p)
        return p

    def _kamera(self, geom, okraj=0.08):
        """Výřez, který útvar ukáže celý v čisté části panelu (mimo měkké okraje a popisky)."""
        x0, y0, x1, y1 = geom.bounds
        w, h = (x1 - x0) * self.KX, (y1 - y0)
        spodek, vrsek = self.cista
        w_v = max(w * (1 + 2 * okraj), h * (1 + 2 * okraj) / (vrsek - spodek) * self.pomer)
        h_v = w_v / self.pomer
        cy = (y0 + y1) / 2 + (0.5 - (spodek + vrsek) / 2) * h_v  # útvar do středu čisté části
        return ((x0 + x1) / 2 * self.KX, cy, w_v)

    @staticmethod
    def _a(p, alpha):
        if p is not None:
            p.set_visible(alpha > 0.005)
            p.set_alpha(min(alpha, 1))

    def kresli(self, pred, akt, t):
        """t = průběh přechodu z `pred` do `akt` (0..1, už s easingem)."""
        for p in self.vse:
            p.set_visible(False)
        (cx0, cy0, w0), (cx1, cy1, w1) = self.kamera[pred], self.kamera[akt]
        cx, cy = cx0 + (cx1 - cx0) * t, cy0 + (cy1 - cy0) * t
        w = math.exp(math.log(w0) + (math.log(w1) - math.log(w0)) * t)
        h = w / self.pomer
        self.ax.set_xlim(cx - w / 2, cx + w / 2)
        self.ax.set_ylim(cy - h / 2, cy + h / 2)

        self._a(self.hranice[pred], 1 - t)
        self._a(self.hranice[akt], t if pred != akt else 1)
        if pred == akt or t >= 1:
            self._a(self.vypln[akt], 1)
            for z, a in zip(self.zare[akt], (0.06, 0.12, 0.9)):
                self._a(z, a)
            return
        d = self.prechody[(pred, akt)]
        if "stary" in d:
            self._a(d["stary"], 1 - t)
            self._a(d["novy"], t)
        else:
            self._a(d["spolecne"], 1)
            self._a(d["ztrata"], 1 - t)
            self._a(d["ztrata_seda"], 0.35 * t)
            self._a(d["nove"], t)
        for z, a in zip(self.zare[pred], (0.06, 0.12, 0.9)):
            self._a(z, a * (1 - t))
        for z, a in zip(self.zare[akt], (0.06, 0.12, 0.9)):
            self._a(z, a * t)


# ---------------------------------------------------------------- šipka trendu
def uhel_z_tempa(r):
    """Roční tempo změny -> úhel šipky. I malý pokles musí být vidět, proto základ 15°."""
    if abs(r) < 1e-5:
        return 0.0
    return math.copysign(min(70.0, 15 + 55 * abs(r) / 0.01), r)


class Sipka:
    """Šipka trendu podle aktuálního ročního tempa změny počtu obyvatel.

    Otáčí se plynule se setrvačností (TAU), takže na změnu v datech reaguje se zpožděním;
    při změně směru (nahoru <-> dolů) krátce zapulzuje.
    """
    TAU = 0.5  # s
    PRAH_PULZU = 25  # úhel cíle (°), od kterého se změna směru bere jako zlom

    def __init__(self, osa):
        self.fps, dt = osa.fps, 1 / osa.fps
        self.uhly, self.meritka = [], []
        uhel, pulz_od = None, -1e9
        for k in range(osa.n):
            cas = k * dt
            rok = osa.rok(cas)
            r = (osa.pocet(rok + 0.5) - osa.pocet(rok - 0.5)) / osa.pocet(rok)
            cil = uhel_z_tempa(r)
            novy = cil if uhel is None else uhel + (cil - uhel) * (1 - math.exp(-dt / self.TAU))
            if uhel is not None and (novy > 0) != (uhel > 0) and abs(cil) > self.PRAH_PULZU:
                pulz_od = cas
            uhel = novy
            t = cas - pulz_od
            self.uhly.append(uhel)
            self.meritka.append(1 + 0.35 * abs(math.sin(t * math.pi * 2.2)) if t < 1.4 else 1.0)

    def stav(self, cas):
        """(úhel, měřítko pulzu)"""
        k = min(int(cas * self.fps + 0.5), len(self.uhly) - 1)
        return self.uhly[k], self.meritka[k]


def tvar_sipky(uhel, meritko):
    body = np.array([(-0.75, 0.16), (0.2, 0.16), (0.2, 0.42), (0.8, 0.0), (0.2, -0.42), (0.2, -0.16), (-0.75, -0.16)])
    a = math.radians(uhel)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return (body * meritko) @ rot.T


def barva_sipky(uhel):
    g, r = np.array(matplotlib.colors.to_rgb(BARVY["nahoru"])), np.array(matplotlib.colors.to_rgb(BARVY["dolu"]))
    s = np.array(matplotlib.colors.to_rgb(BARVY["text2"]))
    f = min(abs(uhel) / 15, 1)
    return tuple(s + ((g if uhel > 0 else r) - s) * f)


# ---------------------------------------------------------------- rozvržení (px, y od horního okraje)
# Pořadí čtení shora dolů: mapa -> název útvaru (s vlajkou) -> letopočet -> počet obyvatel -> událost.
MAPA_Y, MAPA_V = 230, 780          # panel mapy
FADE_HORNI, FADE_DOLNI = 80, 110   # měkké okraje mapy
UTVAR_Y = 1040                     # střed řádku s vlajkou a názvem útvaru
ROK_Y = 1090                       # horní okraj letopočtu
CISLO_Y = 1225                     # horní okraj počtu obyvatel
UDALOST_Y = 1482                   # střed řádku s ikonou a popiskem
ODZNAK_R = 98                      # poloměr odznaku s ikonou
ZDROJE_Y = 1665

# Hook a náhled: první snímek je zároveň obrázek náhledu (Facebook ořezává svislé video ve feedu
# zhruba na 4:5, v mřížce až na 1:1), proto je vše podstatné ve středovém čtverci y 420–1500.
SLOT_STARA = (60, 800, 420, 280)    # x, y, šířka, výška v px
SLOT_NOVA = (600, 800, 420, 280)
H_ODCHOD = (2.7, 3.2)               # úvodní obrazovka drží do 2,7 s, pak se rozplyne do mapy
CERNA, ZLUTA = "#000000", "#ffcc00"
BILA, CERVENA, MODRA = "#ffffff", "#d7141a", "#11457e"
SIPKA_S = 300                       # velikost osy se šipkou trendu (px)


def vlajka_cr(ax):
    """Dnešní vlajka z vektorových tvarů v souřadnicích 0..3 × 0..2."""
    return [ax.add_patch(Rectangle((0, 1), 3, 1, fc=BILA, ec="none")),
            ax.add_patch(Rectangle((0, 0), 3, 1, fc=CERVENA, ec="none")),
            ax.add_patch(Polygon([(0, 0), (0, 2), (1.5, 1)], closed=True, fc=MODRA, ec="none")),
            obrys_vlajky(ax)]


def obrys_vlajky(ax):
    """Jemný obrys, aby černý pruh nesplýval s tmavým pozadím."""
    return ax.add_patch(Rectangle((0, 0), 3, 2, fill=False, ec=BARVY["text2"], lw=1.5, alpha=0.6, zorder=5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jazyk", default="cs")
    ap.add_argument("--nahled", action="store_true")
    ap.add_argument("--snimek", type=float, help="vyrenderuje jen jeden snímek v daném čase (s) do PNG")
    ap.add_argument("--obalka", action="store_true", help="uloží obrázek náhledu (první snímek) a ukázky ořezů")
    args = ap.parse_args()

    tx = json.loads((ROOT / "texty" / f"{args.jazyk}.json").read_text())
    p = tx["popisky"]
    skala, fps = (0.5, 12) if args.nahled else (1.0, 25)
    plt.rcParams.update({"font.family": FONT, "animation.ffmpeg_path": imageio_ffmpeg.get_ffmpeg_exe()})
    pt = 72 / 100  # px -> pt při dpi 100 (škáluje se s figurou)

    osa = Osa(fps)
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100 * skala, facecolor=BARVY["pozadi"])

    # vrstva textů v pixelových souřadnicích (y od shora)
    tax = fig.add_axes([0, 0, 1, 1], zorder=10)
    tax.set_xlim(0, W); tax.set_ylim(H, 0); tax.axis("off")
    T = lambda x, y, s="", **kw: tax.text(x, y, s, **kw)
    titulek = T(W / 2, 195, tx["titulek"], ha="center", va="center", fontsize=26 * pt, color=BARVY["text2"],
                weight="demibold", zorder=8)
    nadpis_t = T(40, MAPA_Y + 18, p["nadpis_mapy"], va="top", fontsize=28 * pt, color=BARVY["text2"],
                 weight="demibold")
    utvar_t = T(178, UTVAR_Y, "", va="center", fontsize=54 * pt, color=BARVY["utvar"], weight="bold")
    rok_t = T(56, ROK_Y, "", va="top", fontsize=118 * pt, color=BARVY["text"], weight="bold")
    cislo_t = T(60, CISLO_Y, "", va="top", fontsize=96 * pt, color=BARVY["text"], weight="bold")

    # událost: ikona v kruhovém odznaku (Font Awesome Free, CC BY 4.0) + popisek
    ikony = json.loads((ROOT / "assets" / "ikony" / "ikony.json").read_text())
    fa = FontProperties(fname=ROOT / "assets" / "ikony" / "fa-solid-900.ttf")
    ox = 60 + ODZNAK_R
    zare_odznaku = [tax.add_patch(Circle((ox, UDALOST_Y), ODZNAK_R + d, fc=BARVY["utvar"], ec="none", zorder=3))
                    for d in (26, 13)]
    odznak = tax.add_patch(Circle((ox, UDALOST_Y), ODZNAK_R, fc=BARVY["utvar"], ec="none", zorder=4))
    ikona_t = T(ox, UDALOST_Y + 4, "", ha="center", va="center", fontproperties=fa, fontsize=94 * pt,
                color=BARVY["pozadi"], zorder=5)
    popis_t = T(ox + ODZNAK_R + 40, UDALOST_Y, "", va="center", fontsize=50 * pt, color=BARVY["text"],
                weight="demibold",
                linespacing=1.25)

    # závěr: pointa s rokem 1930 (zůstane do konce) a zdroje
    d = {int(r.rok): float(r.celkem) for r in osa.radky if r.typ == "scitani"}
    pointa_t = [T(60, UDALOST_Y - 70 + 66 * i, s, va="top", fontsize=50 * pt, weight="bold",
                  color=BARVY["text"]) for i, s in enumerate(tx["pointa"])]
    zdroje_t = T(W / 2, ZDROJE_Y, "\n".join(textwrap.wrap(tx["zdroje"], 60)), ha="center", va="top",
                 fontsize=22 * pt, color=BARVY["text2"], linespacing=1.4)
    autor_t = T(W / 2, ZDROJE_Y + 110, tx["autor"], ha="center", va="top", fontsize=28 * pt, color=BARVY["text"],
                weight="demibold")

    # měkké okraje mapy
    pz = np.array(matplotlib.colors.to_rgb(BARVY["pozadi"]))
    for y0, y1, smer in ((MAPA_Y, MAPA_Y + FADE_HORNI, 1), (MAPA_Y + MAPA_V - FADE_DOLNI, MAPA_Y + MAPA_V, -1)):
        g = np.linspace(1, 0, 64) if smer == 1 else np.linspace(0, 1, 64)
        img = np.concatenate([np.tile(pz, (64, 1, 1)), g[:, None, None] * np.ones((64, 1, 1))], axis=2)
        tax.imshow(img, extent=(0, W, y1, y0), aspect="auto", zorder=1, interpolation="bilinear")
    # clona: během hooku zakrývá vše pod ním
    clona = tax.add_patch(Rectangle((0, 0), W, H, fc=BARVY["pozadi"], ec="none", zorder=7))
    tax.set_xlim(0, W); tax.set_ylim(H, 0)

    # malá vlajka vlevo od názvu útvaru
    fax = fig.add_axes(obdelnik(60, UTVAR_Y - 34, 102, 68), zorder=9)
    fax.axis("off")
    vlajky = {}
    for k in {v for _, v in VLAJKY}:
        img = (np.full((640, 960, 3), 110, np.uint8) if k == "zadna"
               else np.asarray(Image.open(ROOT / "assets" / "vlajky" / f"{k}.png").convert("RGB")))
        vlajky[k] = fax.imshow(img, extent=(0, 960, 640, 0), interpolation="antialiased")
    fax.set_xlim(0, 960); fax.set_ylim(640, 0)

    # úvodní obrazovka (= náhled videa): habsburská vlajka -> dnešní vlajka
    hax = fig.add_axes(obdelnik(*SLOT_STARA), zorder=12)
    hax.set_xlim(0, 3); hax.set_ylim(0, 2); hax.axis("off")
    h_stara = [hax.add_patch(Rectangle((0, 1), 3, 1, fc=CERNA, ec="none")),
               hax.add_patch(Rectangle((0, 0), 3, 1, fc=ZLUTA, ec="none")),
               obrys_vlajky(hax)]
    nax = fig.add_axes(obdelnik(*SLOT_NOVA), zorder=12)
    nax.set_xlim(0, 3); nax.set_ylim(0, 2); nax.axis("off")
    n_vlajka = vlajka_cr(nax)
    rok_od, rok_do = int(osa.roky[0]), int(osa.roky[-1])
    h_roky = [T(x + w / 2, y - 25, str(r), ha="center", va="bottom", fontsize=80 * pt, color=BARVY["text"],
                weight="bold", zorder=12) for (x, y, w, _), r in ((SLOT_STARA, rok_od), (SLOT_NOVA, rok_do))]
    h_sipka = tax.add_patch(Polygon(tvar_sipky(0, 1) * 70 + (540, SLOT_STARA[1] + SLOT_STARA[3] / 2), closed=True,
                                    fc=BARVY["utvar"], ec="none", zorder=12))
    h_otazka = T(W / 2, 1345, tx["hook"], ha="center", va="center", fontsize=58 * pt, color=BARVY["utvar"],
                 weight="bold", zorder=12)
    h_titulek = T(W / 2, 560, tx["titulek"], ha="center", va="center", fontsize=34 * pt, color=BARVY["text2"],
                  weight="demibold", zorder=12)

    # mapa
    mapa_ud = stav_v_case(MAPY, osa, 0)
    max_ = fig.add_axes(obdelnik(0, MAPA_Y, W, MAPA_V), zorder=1)
    mapa = Mapa(max_, [k for _, k in mapa_ud], cista=(FADE_DOLNI / MAPA_V, 1 - FADE_HORNI / MAPA_V))

    def fmt(v, des):
        s = f"{v / 1e6:.{des}f}".replace(".", p["desetinna_carka"])
        return f'{s} {p["mil"]}'

    # šipka trendu hned za počtem obyvatel: pozice podle nejširšího čísla ve videu, aby neposkakovala
    renderer = fig.canvas.get_renderer()
    # dlouhé názvy útvarů (např. v angličtině) se zmenší, aby se vešly na šířku obrazovky
    velikost_utvaru = {}
    for kl, nazev in tx["utvary"].items():
        utvar_t.set_text(nazev); utvar_t.set_fontsize(54 * pt)
        sirka_nazvu = utvar_t.get_window_extent(renderer).width / skala
        velikost_utvaru[kl] = 54 * pt * min(1.0, (W - 178 - 40) / sirka_nazvu)
    sirka = 0
    for rok, v in zip(osa.p_rok, osa.p_cel):
        cislo_t.set_text(("≈ " + fmt(v, 1)) if rok < 1857 else fmt(v, 2))
        sirka = max(sirka, cislo_t.get_window_extent(renderer).width / skala)
    cx, cy = 60 + sirka + 45 + 0.75 / 1.1 * SIPKA_S / 2, CISLO_Y + 52
    sax = fig.add_axes(obdelnik(cx - SIPKA_S / 2, cy - SIPKA_S / 2, SIPKA_S, SIPKA_S), zorder=9)
    sax.set_xlim(-1.1, 1.1); sax.set_ylim(-1.1, 1.1); sax.set_aspect("equal"); sax.axis("off")
    sipka = Sipka(osa)
    sipka_p = Polygon(tvar_sipky(0, 1), closed=True, ec="none")
    sax.add_patch(sipka_p)

    utvar_ud = stav_v_case(UTVARY, osa, 0)
    vlajka_ud = stav_v_case(VLAJKY, osa, 0)

    pointa_t[-1].set_text(p["pointa_cisla"].format(a=fmt(d[1930], 2), b=fmt(d[2021], 2)))
    pointa_t[-1].set_color(BARVY["utvar"]); pointa_t[-1].set_fontsize(38 * pt); pointa_t[-1].set_y(UDALOST_Y + 75)

    def snimek(k):
        cas = k / fps
        rok = osa.rok(cas)
        intro = ease((cas - HOOK) / 0.6)  # náběh mapy, textů a čísel po hooku
        konec = osa.konec_dat

        # úvodní obrazovka: drží a pak se rozplyne do mapy
        a_h = 1 - ease((cas - H_ODCHOD[0]) / (H_ODCHOD[1] - H_ODCHOD[0]))
        hax.set_visible(a_h > 0.005); nax.set_visible(a_h > 0.005)
        for o in (*h_stara, *n_vlajka):
            o.set_alpha(a_h * (0.6 if o in (h_stara[-1], n_vlajka[-1]) else 1))
        for o in (*h_roky, h_sipka, h_otazka, h_titulek):
            o.set_alpha(a_h)
        titulek.set_alpha(intro)
        clona.set_alpha(1 - intro)

        # útvar s vlajkou, letopočet
        pred, akt, t0 = aktualni(utvar_ud, cas)
        f = ease((cas - t0) / 0.5)
        kl = akt if f > 0.5 else pred
        utvar_t.set_text(tx["utvary"][kl]); utvar_t.set_fontsize(velikost_utvaru[kl])
        utvar_t.set_alpha(abs(2 * f - 1) if f < 1 else 1)
        pred, akt, t0 = aktualni(vlajka_ud, cas)
        f = ease((cas - t0) / 0.6)
        for kl, im in vlajky.items():
            a = (f if kl == akt else (1 - f) if kl == pred and pred != akt else 0) * intro
            im.set_visible(a > 0.005); im.set_alpha(a)
        vlajky[akt].set_zorder(2); vlajky[pred].set_zorder(1)
        rok_t.set_text(str(int(round(rok))))

        # událost
        i = osa.radek(cas)
        if i is not None and cas < konec:
            r = osa.radky[i]
            zac, dl = osa.start[i], trvani(r.rok, r.typ)
            a = ease((cas - zac) / 0.25) * (1 - ease((cas - zac - dl + 0.25) / 0.25))
            popis_t.set_text("\n".join(textwrap.wrap(tx["udalosti"][str(r.rok)], 25)))
            popis_t.set_alpha(a)
            barva = BARVY["text2"] if r.rok in TICHE else BARVY["utvar"]  # válečné momenty tlumeně
            mm = ease_back((cas - zac) / 0.45)  # odznak „vyskočí“ s mírným přestřelením
            ikona_t.set_text(chr(int(ikony[r.ikona], 16)))
            ikona_t.set_fontsize(94 * pt * max(mm, 0.01)); ikona_t.set_alpha(a)
            odznak.set_radius(ODZNAK_R * mm); odznak.set_facecolor(barva); odznak.set_alpha(a)
            for z, al in zip(zare_odznaku, (0.08, 0.18)):
                z.set_radius((ODZNAK_R + (26 if al < 0.1 else 13)) * mm); z.set_facecolor(barva); z.set_alpha(a * al)
        else:
            popis_t.set_alpha(0); ikona_t.set_alpha(0); odznak.set_alpha(0)
            for z in zare_odznaku:
                z.set_alpha(0)

        # závěr: pointa (1930 vs. 2021) postupně po řádcích a zůstane do konce, pak zdroje
        for j, z in enumerate(pointa_t):
            z.set_alpha(ease((cas - konec - 0.3 - 0.5 * j) / 0.5))
        a_z = ease((cas - konec - 2.0) / 0.8)
        zdroje_t.set_alpha(a_z); autor_t.set_alpha(a_z)

        # mapa
        pred, akt, t0 = aktualni(mapa_ud, cas)
        mapa.kresli(pred, akt, ease((cas - t0) / 1.0))

        # počet obyvatel a šipka; odhady (před 1857) tlumeně a se „≈“
        v = osa.pocet(rok)
        odhad = rok < 1857
        cislo_t.set_text(("≈ " + fmt(v, 1)) if odhad else fmt(v, 2))
        cislo_t.set_color(BARVY["text2"] if odhad else BARVY["text"])
        uhel, mer = sipka.stav(cas)
        sipka_p.set_xy(tvar_sipky(uhel, mer))
        sipka_p.set_facecolor(barva_sipky(uhel))
        sipka_p.set_alpha(intro)

    if args.obalka:
        uloz_obalku(fig, snimek, args.jazyk)
        return
    if args.snimek is not None:
        snimek(int(args.snimek * fps))
        out = ROOT / "assets" / "video" / f"snimek_{args.jazyk}_{args.snimek:.1f}s.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, facecolor=BARVY["pozadi"])
        print(out)
        return

    out = ROOT / "assets" / "video" / f"cesko_v_cislech_{args.jazyk}{'_nahled' if args.nahled else ''}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p", "-crf", "20"])
    with writer.saving(fig, str(out), dpi=100 * skala):
        for k in range(osa.n):
            snimek(k)
            writer.grab_frame(facecolor=BARVY["pozadi"])
            if k % (fps * 5) == 0:
                print(f"{k / fps:5.1f} / {osa.delka:.1f} s", flush=True)
    print(out, f"{osa.delka:.1f} s")


def uloz_obalku(fig, snimek, jazyk):
    """Obrázek náhledu (= první snímek videa) a ukázka, jak ho oříznou feed (4:5) a mřížka (1:1)."""
    snimek(0)
    out = ROOT / "assets" / "video" / f"obalka_{jazyk}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BARVY["pozadi"], dpi=100)
    img = Image.open(out).convert("RGB")
    orezy = [("9:16 (celá obrazovka)", img),
             ("4:5 (feed)", img.crop((0, (H - 1350) // 2, W, (H + 1350) // 2))),
             ("1:1 (mřížka)", img.crop((0, (H - 1080) // 2, W, (H + 1080) // 2)))]
    vyska = 640
    dily = [o.resize((int(o.width * vyska / o.height), vyska)) for _, o in orezy]
    plocha = Image.new("RGB", (sum(x.width for x in dily) + 40 * (len(dily) + 1), vyska + 90), "white")
    from PIL import ImageDraw, ImageFont
    kresli = ImageDraw.Draw(plocha)
    pismo = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 26)
    x = 40
    for (nazev, _), dil in zip(orezy, dily):
        plocha.paste(dil, (x, 70))
        kresli.text((x, 22), nazev, fill="black", font=pismo)
        x += dil.width + 40
    plocha.save(ROOT / "assets" / "video" / f"obalka_{jazyk}_orezy.png")
    print(out)


if __name__ == "__main__":
    main()
