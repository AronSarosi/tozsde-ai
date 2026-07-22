"""Per-stock historical test: would the system have made money trading EACH
stock alone over ~10 years, vs simply buying and holding that same stock?

Strategy per stock (price-sleeve of the live formula): be invested while the
momentum score >= enter_th; go to cash when score <= exit_th or a trailing
stop from the post-entry peak is hit. Walk-forward: optimize on 2016-2022,
validate 2023-today. Iterative random search; progress + results written to
backtest/per_stock_results.json and backtest/PER_STOCK_REPORT.md.

Run: python backtest/per_stock.py [n_iter]  (default 60). Read-only DB access.
"""
from __future__ import annotations
import json, random, sqlite3, sys
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

def score(close: pd.Series, p: dict) -> pd.Series:
    raw = (close.pct_change(63) * p["w_r3"] + close.pct_change(126) * p["w_r6"]
           + (close / close.rolling(50).mean() - 1) * p["w_ma50"]
           + (close / close.rolling(200).mean() - 1) * p["w_ma200"])
    return (50 + raw * p["scale"]).clip(0, 100)

def sim(close: pd.Series, sc: pd.Series, p: dict, start: str, end: str) -> dict | None:
    c = close[(close.index >= start) & (close.index <= end)].dropna()
    if len(c) < 260:
        return None
    s = sc.reindex(c.index)
    equity, in_pos, peak, entry_d, trades, days_in = 1.0, False, 0.0, None, 0, 0
    prev = None
    for d, px in c.items():
        if prev is not None and in_pos:
            equity *= px / prev
            days_in += 1
            peak = max(peak, px)
            if px / peak - 1 <= p["trail"] or (not pd.isna(s[d]) and s[d] <= p["exit_th"]):
                in_pos = False
                trades += 1
        elif not in_pos and not pd.isna(s[d]) and s[d] >= p["enter_th"]:
            in_pos, peak = True, px
        prev = px
    bh = c.iloc[-1] / c.iloc[0] - 1
    return {"strat": round((equity - 1) * 100, 1), "bh": round(bh * 100, 1),
            "edge": round((equity - 1 - bh) * 100, 1), "trades": trades,
            "time_in": round(100 * days_in / len(c))}

def rand_cfg(rng: random.Random) -> dict:
    w = [rng.random() for _ in range(4)]; t = sum(w)
    return {"w_r3": round(w[0]/t, 3), "w_r6": round(w[1]/t, 3), "w_ma50": round(w[2]/t, 3),
            "w_ma200": round(w[3]/t, 3), "scale": rng.choice([80, 100, 130, 160]),
            "enter_th": rng.choice([52, 55, 58, 62]), "exit_th": rng.choice([38, 42, 45, 48]),
            "trail": rng.choice([-0.10, -0.15, -0.20, -0.25])}

LIVE = {"w_r3": 0.4, "w_r6": 0.3, "w_ma50": 0.15, "w_ma200": 0.15,
        "scale": 130, "enter_th": 58, "exit_th": 45, "trail": -0.15}

def evaluate(mat: pd.DataFrame, cfg: dict, start: str, end: str) -> dict:
    per = {}
    for sym in mat.columns:
        if sym == "SPY":
            continue
        r = sim(mat[sym], score(mat[sym], cfg), cfg, start, end)
        if r:
            per[sym] = r
    ser = pd.Series({k: v["strat"] for k, v in per.items()})
    edge = pd.Series({k: v["edge"] for k, v in per.items()})
    return {"n": len(per), "median_ret": round(float(ser.median()), 1),
            "pct_profitable": round(100 * float((ser > 0).mean())),
            "median_edge_vs_bh": round(float(edge.median()), 1),
            "pct_beat_bh": round(100 * float((edge > 0).mean())), "per_stock": per}

def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    mat = load()
    first = mat.index[0]
    rng = random.Random(7)
    rows = []
    def run(cfg, tag):
        tr = evaluate(mat, cfg, first, TRAIN_END)
        te = evaluate(mat, cfg, TRAIN_END, mat.index[-1])
        rows.append({"tag": tag, "cfg": cfg,
                     "train": {k: v for k, v in tr.items() if k != "per_stock"},
                     "test": {k: v for k, v in te.items() if k != "per_stock"},
                     "test_per_stock": te["per_stock"]})
        print(f"[{tag}] TRAIN med ret {tr['median_ret']:+.1f}% prof {tr['pct_profitable']}% beatBH {tr['pct_beat_bh']}%"
              f" | TEST med ret {te['median_ret']:+.1f}% prof {te['pct_profitable']}% beatBH {te['pct_beat_bh']}%")
        (OUT / "per_stock_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    run(LIVE, "LIVE-LIKE")
    for i in range(n):
        run(rand_cfg(rng), f"rand-{i+1:02d}")
    best = max(rows[1:], key=lambda r: r["train"]["median_ret"] + r["train"]["pct_beat_bh"] * 0.1)
    base = rows[0]
    lines = ["# Per-stock backtest report", "",
             f"Universe: {base['train']['n']} stocks | TRAIN {first}..{TRAIN_END} | TEST ..{mat.index[-1]}", "",
             f"BASELINE train: {base['train']} | test: {base['test']}",
             f"BEST ({best['tag']}) train: {best['train']} | test: {best['test']}",
             f"BEST config: {best['cfg']}", "", "## Best config, TEST window, key stocks", ""]
    for sym in ["AAPL", "MSFT", "TSLA", "NVDA", "META", "GOOGL", "AMZN", "TSM", "MU", "INTC"]:
        r = best["test_per_stock"].get(sym)
        if r:
            lines.append(f"- {sym}: strategy {r['strat']:+.1f}% vs buy&hold {r['bh']:+.1f}% "
                         f"(edge {r['edge']:+.1f}pp, {r['trades']} trades, {r['time_in']}% time in market)")
    (OUT / "PER_STOCK_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8]))
    print("Full report: backtest/PER_STOCK_REPORT.md")

if __name__ == "__main__":
    main()
