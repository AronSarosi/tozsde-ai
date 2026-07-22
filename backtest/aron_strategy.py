"""Aron-philosophy backtest: long-only, buy relative lows after stabilization,
never sell at a loss (capital may stay locked), take profit only near relative
highs. Tested per stock vs buy-and-hold; TSLA is the acid test.

Run: python backtest/aron_strategy.py [n_iter]  (default 80)
Outputs: backtest/aron_results.json + backtest/ARON_REPORT.md
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

def sim(close: pd.Series, p: dict, start: str, end: str) -> dict | None:
    c = close.dropna()
    if len(c) < 300:
        return None
    lo = c.rolling(p["lb"]).min(); hi = c.rolling(p["lb"]).max()
    rngpos = ((c - lo) / (hi - lo)).fillna(0.5)
    ret1 = c.pct_change()
    stab = (ret1.rolling(p["stab"]).min() > -0.03) & (c.pct_change(p["stab"]) > -0.005)
    w = (c.index >= start) & (c.index <= end)
    idx = c.index[w]
    if len(idx) < 260:
        return None
    equity, in_pos, entry, prev = 1.0, False, 0.0, None
    trades, wins, days_in = 0, 0, 0
    worst_open = 0.0
    for d in idx:
        px = c[d]
        if in_pos:
            if prev is not None:
                equity *= px / prev
            days_in += 1
            r = px / entry - 1
            worst_open = min(worst_open, r)
            if r >= p["min_profit"] and rngpos[d] >= p["exit_pos"]:
                in_pos = False
                trades += 1
                wins += 1
        elif rngpos[d] <= p["entry_pos"] and bool(stab[d]):
            in_pos, entry = True, px
        prev = px
    open_ret = (c[idx[-1]] / entry - 1) if in_pos else None
    bh = c[idx[-1]] / c[idx[0]] - 1
    return {"strat": round((equity - 1) * 100, 1), "bh": round(bh * 100, 1),
            "edge": round((equity - 1 - bh) * 100, 1), "round_trips": trades,
            "realized_losses": 0, "open_pos_ret": None if open_ret is None else round(open_ret * 100, 1),
            "worst_open_dd": round(worst_open * 100, 1), "time_in": round(100 * days_in / len(idx))}

def rand_cfg(rng: random.Random) -> dict:
    return {"lb": rng.choice([252, 378, 504]),
            "entry_pos": rng.choice([0.10, 0.20, 0.30]),
            "stab": rng.choice([5, 8, 12]),
            "min_profit": rng.choice([0.20, 0.35, 0.50]),
            "exit_pos": rng.choice([0.70, 0.80, 0.90, 2.0])}  # 2.0 = never take profit, pure hold after entry

def evaluate(mat: pd.DataFrame, cfg: dict, start: str, end: str) -> dict:
    per = {}
    for sym in mat.columns:
        if sym == "SPY":
            continue
        r = sim(mat[sym], cfg, start, end)
        if r:
            per[sym] = r
    st = pd.Series({k: v["strat"] for k, v in per.items()})
    ed = pd.Series({k: v["edge"] for k, v in per.items()})
    return {"n": len(per), "median_ret": round(float(st.median()), 1),
            "pct_profitable": round(100 * float((st >= 0).mean())),
            "median_edge": round(float(ed.median()), 1),
            "pct_beat_bh": round(100 * float((ed > 0).mean())),
            "tsla": per.get("TSLA"), "per_stock": per}

def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    mat = load()
    rng = random.Random(11)
    rows = []
    def run(cfg, tag):
        tr = evaluate(mat, cfg, mat.index[0], TRAIN_END)
        te = evaluate(mat, cfg, TRAIN_END, mat.index[-1])
        rows.append({"tag": tag, "cfg": cfg,
                     "train": {k: v for k, v in tr.items() if k != "per_stock"},
                     "test": {k: v for k, v in te.items() if k != "per_stock"},
                     "test_per_stock": te["per_stock"]})
        t = te.get("tsla") or {}
        print(f"[{tag}] TRAIN med {tr['median_ret']:+.1f}% prof {tr['pct_profitable']}%"
              f" | TEST med {te['median_ret']:+.1f}% prof {te['pct_profitable']}% beatBH {te['pct_beat_bh']}%"
              f" | TSLA test {t.get('strat')}% vs bh {t.get('bh')}%")
        (OUT / "aron_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for i in range(n):
        run(rand_cfg(rng), f"cfg-{i+1:02d}")
    best = max(rows, key=lambda r: r["train"]["median_ret"] + (r["train"].get("tsla") or {}).get("strat", 0) * 0.01)
    lines = ["# Aron-philosophy strategy report", "",
             f"Rules: long-only, buy when price in bottom of trailing range after stabilization,",
             "never sell at a loss, take profit only near relative highs (or pure hold).", "",
             f"BEST ({best['tag']}): {best['cfg']}",
             f"TRAIN: {best['train']}", f"TEST: {best['test']}", "",
             "## Best config, TEST window (2023-2026), key stocks", ""]
    for sym in ["TSLA", "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSM", "MU", "INTC"]:
        r = best["test_per_stock"].get(sym)
        if r:
            lines.append(f"- {sym}: strategy {r['strat']:+.1f}% vs buy&hold {r['bh']:+.1f}% | "
                         f"{r['round_trips']} profitable exits, 0 realized losses, "
                         f"worst open drawdown {r['worst_open_dd']}%, {r['time_in']}% time in market"
                         + (f", open pos at {r['open_pos_ret']:+.1f}%" if r['open_pos_ret'] is not None else ""))
    (OUT / "ARON_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\nReport: backtest/ARON_REPORT.md")

if __name__ == "__main__":
    main()
