"""Granular grid backtest: ~120 precisely-defined scenarios.

Entry (concrete definitions):
  DD-X:  price >= X% below its 252-day high (X in 5,10,15,20,30)
  RNG-Y: price in the bottom Y% of its 252-day low-high range (Y in 10,20,30,40)
  ALWAYS: invested from day one (buy-and-hold)
  BREAKOUT: price in top 10% of 252-day range
Stabilization filter (applied to dip entries):
  none  - buy immediately (falling knife accepted)
  calmN - last N days: no single day worse than -3% AND sum of N returns > -0.5%
  ma20  - price back above its 20-day average (recovery confirmed)
Exit:
  NEVER - hold forever, losses never realized
  CAT50 - only exception: exit at -50% from entry (catastrophe brake)
  BAND  - take profit when >= +35% AND price in top 15% of range

Run: python backtest/grid.py -> backtest/GRID_REPORT.md (top list + key stocks)
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
TRAIN_END = "2022-12-31"
KEY = ["TSLA", "NVDA", "AMZN", "INTC"]

def load() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{ROOT/'data'/'tozsde_ai.db'}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT symbol, date, close FROM prices_daily", con)
    con.close()
    return df.pivot(index="date", columns="symbol", values="close").sort_index()

def prep(c: pd.Series) -> dict:
    lo, hi = c.rolling(252).min(), c.rolling(252).max()
    r1 = c.pct_change()
    return {"rng": ((c - lo) / (hi - lo)).fillna(0.5),
            "dd": (c / hi - 1).fillna(0),
            "calm3": (r1.rolling(3).min() > -0.03) & (c.pct_change(3) > -0.005),
            "calm5": (r1.rolling(5).min() > -0.03) & (c.pct_change(5) > -0.005),
            "calm10": (r1.rolling(10).min() > -0.03) & (c.pct_change(10) > -0.005),
            "ma20": c > c.rolling(20).mean()}

ENTRIES = ([("DD-%d%%" % x, ("dd", -x / 100)) for x in (5, 10, 15, 20, 30)]
           + [("RNG-%d%%" % y, ("rng", y / 100)) for y in (10, 20, 30, 40)])
STABS = ["none", "calm3", "calm5", "calm10", "ma20"]
EXITS = ["NEVER", "CAT50", "BAND"]

def scenarios():
    yield "ALWAYS (buy&hold)", None, "none", "NEVER"
    yield "BREAKOUT top10% + NEVER", ("brk", 0.90), "none", "NEVER"
    yield "BREAKOUT top10% + BAND", ("brk", 0.90), "none", "BAND"
    for ename, econd in ENTRIES:
        for stab in STABS:
            for ex in EXITS:
                yield f"{ename} + {stab} + {ex}", econd, stab, ex

def sim(c: pd.Series, ind: dict, econd, stab: str, ex: str, start, end):
    c = c.dropna()
    idx = c.index[(c.index >= start) & (c.index <= end)]
    if len(idx) < 260:
        return None
    eq, in_pos, ent, prev, days_in = 1.0, False, 0.0, None, 0
    for d in idx:
        px = c[d]
        if in_pos:
            if prev is not None:
                eq *= px / prev
            days_in += 1
            r = px / ent - 1
            if (ex == "CAT50" and r <= -0.50) or (ex == "BAND" and r >= 0.35 and ind["rng"][d] >= 0.85):
                in_pos = False
        else:
            if econd is None:
                ok = True
            elif econd[0] == "dd":
                ok = ind["dd"][d] <= econd[1]
            elif econd[0] == "brk":
                ok = ind["rng"][d] >= econd[1]
            else:
                ok = ind["rng"][d] <= econd[1]
            if ok and (stab == "none" or bool(ind[stab][d])):
                in_pos, ent = True, px
        prev = px
    bh = c[idx[-1]] / c[idx[0]] - 1
    return {"strat": (eq - 1) * 100, "bh": bh * 100, "time_in": 100 * days_in / len(idx)}

def main() -> None:
    mat = load()
    inds = {s: prep(mat[s].dropna()) for s in mat.columns if s != "SPY" and mat[s].dropna().size >= 300}
    rows = []
    for name, econd, stab, ex in scenarios():
        res = {}
        for win, (a, b) in {"train": (mat.index[0], TRAIN_END), "test": (TRAIN_END, mat.index[-1])}.items():
            per = {}
            for s, ind in inds.items():
                r = sim(mat[s], ind, econd, stab, ex, a, b)
                if r:
                    per[s] = r
            st = pd.Series({k: v["strat"] for k, v in per.items()})
            res[win] = {"median": round(float(st.median()), 1),
                        "profitable": round(100 * float((st >= 0).mean())),
                        "time_in": round(float(pd.Series({k: v["time_in"] for k, v in per.items()}).median())),
                        **{k: (round(per[k]["strat"], 1) if k in per else None) for k in KEY}}
        rows.append({"name": name, **res})
        print(f"{name} | TEST med {res['test']['median']:+.1f}% prof {res['test']['profitable']}%")
    rows.sort(key=lambda r: r["test"]["median"], reverse=True)
    (OUT / "grid_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    lines = [f"# Grid backtest - {len(rows)} pontosan definialt szcenario", "",
             "TEST = 2023-2026 (out-of-sample). Oszlopok: median hozam, profitabilis reszvenyek, ido a piacon, TSLA/NVDA/AMZN/INTC.", "",
             "| # | Szabalyrendszer | Median | Prof% | Piacon% | TSLA | NVDA | AMZN | INTC | TRAIN med |", "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:20], 1):
        t = r["test"]
        lines.append(f"| {i} | {r['name']} | {t['median']:+.1f}% | {t['profitable']}% | {t['time_in']}% |"
                     f" {t['TSLA']}% | {t['NVDA']}% | {t['AMZN']}% | {t['INTC']}% | {r['train']['median']:+.1f}% |")
    lines += ["", "## Sereghajtok (utolso 5)", ""]
    for r in rows[-5:]:
        lines.append(f"- {r['name']}: TEST {r['test']['median']:+.1f}%")
    (OUT / "GRID_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(rows)} scenarios done. Report: backtest/GRID_REPORT.md")

if __name__ == "__main__":
    main()
