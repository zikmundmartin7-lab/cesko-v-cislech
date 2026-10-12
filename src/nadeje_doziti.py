"""Naděje dožití při narození podle pohlaví -> data/nadeje_doziti.csv a sloupce v data/timeline.csv.

Zdroj: ČSÚ, Demografická příručka 2024, tab. 8.6 (roky 1920–2024; ve válečných letech 1938–1944
vypočteno z dat za české obyvatelstvo na území Protektorátu Čechy a Morava).
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

x = pd.read_excel(ROOT / "data" / "raw" / "csu_dp2024_8-06_nadeje_doziti.xlsx", header=None)
x = x[pd.to_numeric(x[0], errors="coerce").notna()].iloc[:, :2]
x.columns = ["rok", "e0"]
x["rok"] = x.rok.astype(int)
x["e0"] = x.e0.astype(float)
polovina = len(x) // 2  # tabulka má nejdřív muže, pak ženy
muzi = x.iloc[:polovina].set_index("rok")["e0"]
zeny = x.iloc[polovina:].set_index("rok")["e0"]
assert list(muzi.index) == list(zeny.index) == list(range(1920, 2025))

out = pd.DataFrame({"rok": muzi.index, "nadeje_doziti_muzi": muzi.round(2).values,
                    "nadeje_doziti_zeny": zeny.round(2).values})
out["poznamka"] = ["české obyvatelstvo Protektorátu" if 1938 <= r <= 1944 else "" for r in out.rok]
out.to_csv(ROOT / "data" / "nadeje_doziti.csv", index=False)

# sloupce v osě videu: hodnota za rok datového bodu (sčítání od roku 1921)
t = pd.read_csv(ROOT / "data" / "timeline.csv", keep_default_na=False, dtype=str)
for sl, rada in (("nadeje_doziti_muzi", muzi), ("nadeje_doziti_zeny", zeny)):
    t[sl] = [f"{rada[int(r)]:.2f}" if typ != "udalost" and int(r) in rada.index else ""
             for r, typ in zip(t.rok, t.typ)]
t.to_csv(ROOT / "data" / "timeline.csv", index=False)
print(out[out.rok.isin([1920, 1930, 1960, 1990, 2019, 2021])].to_string(index=False))
