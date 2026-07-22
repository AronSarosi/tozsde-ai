"""Multi-philosophy backtest: named rule sets tested per stock over 10 years.

Each rule set = an entry rule + an exit rule. Ranked by median return across
the universe, % of stocks profitable, and edge vs buy-and-hold, on both the
train (2016-2022) and validation (2023-today) windows.

Run: python backtest/rulesets.py -> backtest/RULESETS_REPORT.md
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
TRAIN_END = "2022-12-31"

def load() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{ROOT/'data'/'tozsde_ai.db'}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT symbol, date, close FROM prices_daily", con)
    con.close()
    return df.pivot(index="date", columns="symbol", values="close").sort_index()

def indicators(c: pd.Series, lb: int) -> dict:
    lo, hi = c.rolling(lb).min(), c.rolling(lb).max()
    return {
        "rng": ((c - lo) / (hi - lo)).fillna(0.5),
        "ret1": c.pct_change(),
        "ma200": c / c.rolling(200).mean() - 1,
        "dd": c / c.rolling(lb).max() - 1,
    }

def calm(ind, d, days, worst=-0.03, total=-0.005):
    r = ind["ret1"]
    w = r.loc[:d].tail(days)
    return len(w) == days and w.min() > worst and w.sum() > total

# Rule sets: (name, lookback, entry(ind,d)->bool, exit(ind,d,ret_since_entry)->bool)
RULESETS = [
    ("BUY-AND-HOLD: vedd meg az elején, tartsd", 252,
     lambda i, d: True, lambda i, d, r: False),
    ("MOMENTUM-TIMING (régi rendszer): trendben bent, trend törésekor ki", 252,
     lambda i, d: i["ma200"][d] > 0.02, lambda i, d, r: i["ma200"][d] < -0.02),
    ("DIP-HOLD 1 év: alsó 30%-ban véve 5 nyugodt nap után, soha nem ad el", 252,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 5), lambda i, d, r: False),
    ("DIP-HOLD 2 év: alsó 30%, 5 nyugodt nap, soha nem ad el", 504,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 5), lambda i, d, r: False),
    ("DIP-HOLD 3 év: alsó 30%, 5 nyugodt nap, soha nem ad el", 756,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 5), lambda i, d, r: False),
    ("DIP-HOLD gyors stabilizáció (3 nap)", 252,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 3), lambda i, d, r: False),
    ("DIP-HOLD lassú stabilizáció (20 nap)", 252,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 20), lambda i, d, r: False),
    ("DIP-HOLD stabilizáció nélkül (zuhanó kést is vesz)", 252,
     lambda i, d: i["rng"][d] <= 0.30, lambda i, d, r: False),
    ("MÉLY-DIP: csak -25%+ esés után, 5 nyugodt nap (COVID-szabály)", 252,
     lambda i, d: i["dd"][d] <= -0.25 and calm(i, d, 5), lambda i, d, r: False),
    ("ARON-SÁVKERESKEDÉS: alsó 30%-ban vesz, felső 85%-ban ÉS 35%+ profitban ad el", 252,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 5),
     lambda i, d, r: r >= 0.35 and i["rng"][d] >= 0.85),
    ("SÁVKERESKEDÉS türelmetlen: 20% profitnál a sáv tetején ad el", 252,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 5),
     lambda i, d, r: r >= 0.20 and i["rng"][d] >= 0.75),
    ("CSÚCSVÉTEL-HOLD: felső 10%-ban (kitörésnél) vesz, soha nem ad el", 252,
     lambda i, d: i["rng"][d] >= 0.90, lambda i, d, r: False),
    ("VESZTESÉG-PLAFON: dip-vétel, de -50%-nál mégis kiszáll (katasztrófa-fék)", 252,
     lambda i, d: i["rng"][d] <= 0.30 and calm(i, d, 5), lambda i, d, r: r <= -0.50),
]

def sim(c: pd.Series, lb, entry, exit_, start, end) -> dict | None:
    c = c.dropna()
    if len(c) < 300:
        return None
    ind = indicators(c, lb)
    idx = c.index[(c.index >= start) & (c.index <= end)]
    if len(idx) < 260:
        return None
    eq, in_pos, ent, prev, worst = 1.0, False, 0.0, None, 0.0
    days_in = 0
    for d in idx:
        px = c[d]
        if in_pos:
            if prev is not None:
                eq *= px / prev
            days_in += 1
            r = px / ent - 1
            worst = min(worst, r)
            if exit_(ind, d, r):
                in_pos = False
        elif entry(ind, d):
            in_pos, ent = True, px
        prev = px
    bh = c[idx[-1]] / c[idx[0]] - 1
    return {"strat": (eq - 1) * 100, "bh": bh * 100, "edge": (eq - 1 - bh) * 100,
            "worst": worst * 100, "time_in": 100 * days_in / len(idx)}

def main() -> None:
    mat = load()
    rows = []
    for name, lb, entry, exit_ in RULESETS:
        res = {}
        for win, (a, b) in {"train": (mat.index[0], TRAIN_END),
                            "test": (TRAIN_END, mat.index[-1])}.items():
            per = {s: r for s in mat.columns if s != "SPY"
                   for r in [sim(mat[s], lb, entry, exit_, a, b)] if r}
            st = pd.Series({k: v["strat"] for k, v in per.items()})
            ed = pd.Series({k: v["edge"] for k, v in per.items()})
            res[win] = {"median": round(float(st.median()), 1),
                        "profitable": round(100 * float((st >= 0).mean())),
                        "beat_bh": round(100 * float((ed > 0).mean())),
                        "tsla": round(per["TSLA"]["strat"], 1) if "TSLA" in per else None,
                        "worst_med": round(float(pd.Series({k: v["worst"] for k, v in per.items()}).median()), 1)}
        rows.append({"name": name, **res})
        print(f"{name} | train med {res['train']['median']:+.1f}% | TEST med {res['test']['median']:+.1f}%"
              f" prof {res['test']['profitable']}% TSLA {res['test']['tsla']}%")
    rows.sort(key=lambda r: r["test"]["median"], reverse=True)
    lines = ["# Szabályrendszer-verseny (10 év, ~100 részvény)", "",
             "| Rangsor | Filozófia | TESZT medián hozam | Profitábilis | TSLA | Legmélyebb átmeneti mínusz (medián) | TRAIN medián |",
             "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lines.append(f"| {i} | {r['name']} | {r['test']['median']:+.1f}% | {r['test']['profitable']}% |"
                     f" {r['test']['tsla']:+.1f}% | {r['test']['worst_med']:.1f}% | {r['train']['median']:+.1f}% |")
    (OUT / "RULESETS_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "rulesets_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\nReport: backtest/RULESETS_REPORT.md")

if __name__ == "__main__":
    main()
