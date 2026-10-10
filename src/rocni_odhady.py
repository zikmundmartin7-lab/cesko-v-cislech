"""Roční počty obyvatel mezi sčítáními v obdobích válek -> data/rocni_odhady.csv.

Mezi sčítáními počítadlo ve videu jinak lineárně dopočítává. Ve válečných obdobích by to
zkreslovalo průběh (např. mezi 1930 a 1950 by počet klesal už od roku 1930, ve skutečnosti rostl
až do roku 1940 a propadl se až v letech 1945–1947). Proto se tam použijí roční údaje ČSÚ.

Zdroje (ČSÚ, Demografická příručka 2024):
  - tab. 1.5a: střední stav obyvatel na území Česka 1919–2024 -> roky 1919–1920 a 1931–1949,
  - tab. 1.3: střední stav na historickém území Čech, Moravy a Slezska 1785–1918 -> tvar křivky 1911–1917.
    Území se liší (a v letech 1914–1918 zahrnuje ze Slezska jen Opavsko), proto je řada přepočtena
    poměrem: 1911–1913 k výsledku sčítání 1910 (dnešní území), 1914–1918 k střednímu stavu 1919
    (dnešní území). Jde o dopočet, ne o publikovaný údaj ČSÚ.

Střední stav = stav k 1. 7., ve videu se umisťuje na rok + 0,5.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def stredni_stav(soubor):
    x = pd.read_excel(RAW / soubor, header=None)
    x = x[pd.to_numeric(x[0], errors="coerce").notna()].iloc[:, :2]
    x.columns = ["rok", "stredni_stav"]
    return x.astype(int).set_index("rok")["stredni_stav"]


cr = stredni_stav("csu_dp2024_1-05a_pohyb_1920_2024.xlsx")   # dnešní území
hist = stredni_stav("csu_dp2024_1-03_pohyb_1785_1918.xlsx")  # historické území
sc1910 = pd.read_csv(ROOT / "data" / "scitani_1869_2021.csv").set_index("rok").loc[1910, "celkem"]

radky = []
k1 = sc1910 / hist[1910]
for r in range(1911, 1914):
    radky.append((r, round(hist[r] * k1), "dopočet z tab. 1.3 (poměr ke sčítání 1910)"))
k2 = cr[1919] / hist[1918]
for r in range(1914, 1918):  # rok 1918 vynechán: poměr je k němu ukotven, splýval by s rokem 1919
    radky.append((r, round(hist[r] * k2), "dopočet z tab. 1.3 (poměr ke střednímu stavu 1919)"))
for r in (1919, 1920, *range(1931, 1950)):
    radky.append((r, int(cr[r]), "ČSÚ DP 2024 tab. 1.5a, střední stav"))

out = pd.DataFrame(radky, columns=["rok", "stredni_stav", "zdroj"])
out.to_csv(ROOT / "data" / "rocni_odhady.csv", index=False)
print(out.to_string(index=False))
