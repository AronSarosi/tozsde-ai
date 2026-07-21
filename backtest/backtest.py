"""Standalone backtest lab - SEPARATE from the live system (read-only DB access).

Replays the shadow-portfolio strategy (daily $1000 x top-5 signals, long+short)
over 10 years of prices and iteratively optimizes the price-based parameters:
momentum mix, risk weight, entry thresholds, stop/target/max-hold.

Walk-forward protocol against overfitting:
  TRAIN  2016-07 .. 2022-12  - random search picks candidate configs
  TEST   2023-01 .. today    - out-of-sample validation of the top configs
Only configs that beat SPY on BOTH windows count as improvements.

Limitation (by data availability): fundamentals/analyst/news exist only as
current snapshots, so this tunes the momentum/risk sleeve of the live formula.

Run: python backtest/backtest.py [n_iterations]   (default 24)
Output: backtest/results.json + console log. Never writes to the live DB.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "tozsde_ai.db"
OUT = Path(__file__).resolve().parent / "results.json"
TRAIN_END = "2022-12-31"
LOT = 1000.0
PICKS = 5


def load_closes() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT symbol, date, close FROM prices_daily", con)
    con.close()
    mat = df.pivot(index="date", columns="symbol", values="close").sort_index()
    return mat


def scores_matrix(closes: pd.DataFrame, p: dict) -> pd.DataFrame:
    r3 = closes.pct_change(63)
    r6 = closes.pct_change(126)
    ma50 = closes / closes.rolling(50).mean() - 1
    ma200 = closes / closes.rolling(200).mean() - 1
    mom_raw = r3 * p["w_r3"] + r6 * p["w_r6"] + ma50 * p["w_ma50"] + ma200 * p["w_ma200"]
    mom = (50 + mom_raw * p["mom_scale"]).clip(3, 97)
    vol = closes.pct_change().rolling(60).std()
    dd = closes / closes.rolling(252, min_periods=60).max() - 1
    risk = ((88 - vol * 1400) + dd * 45).clip(5, 95)
    score = mom * p["w_mom"] + risk * (1 - p["w_mom"])
    return 50 + (score - 50) * 1.6


def simulate(closes: pd.DataFrame, scores: pd.DataFrame, spy: pd.Series,
             p: dict, start: str, end: str) -> dict:
    dates = [d for d in closes.index if start <= d <= end]
    lots: list[dict] = []
    realized = 0.0
    invested = 0.0
    spy_units = 0.0
    spy_invested = 0.0
    daily_pnl = []
    prev_equity = 0.0
    for d in dates:
        px = closes.loc[d]
        sc = scores.loc[d]
        # exits
        keep = []
        for lot in lots:
            cur = px.get(lot["sym"])
            if cur is None or pd.isna(cur):
                keep.append(lot)
                continue
            direction = 1 if lot["side"] == "l" else -1
            ret = (cur / lot["entry"] - 1) * direction
            lot["age"] += 1
            s = sc.get(lot["sym"])
            flip = (not pd.isna(s)) and ((lot["side"] == "l" and s <= p["short_th"]) or
                                         (lot["side"] == "s" and s >= p["long_th"]))
            if ret >= p["target"] or ret <= p["stop"] or lot["age"] >= p["max_hold"] or flip:
                realized += LOT * ret
            else:
                keep.append(lot)
        lots = keep
        # entries: top-5 by |score-50| among candidates
        cand = []
        for sym, s in sc.items():
            if pd.isna(s) or pd.isna(px.get(sym)):
                continue
            if s >= p["long_th"]:
                cand.append((abs(s - 50), sym, "l"))
            elif s <= p["short_th"]:
                cand.append((abs(s - 50), sym, "s"))
        cand.sort(reverse=True)
        for _, sym, side in cand[:PICKS]:
            lots.append({"sym": sym, "side": side, "entry": px[sym], "age": 0})
            invested += LOT
        sp = spy.get(d)
        if not pd.isna(sp):
            spy_units += (LOT * PICKS) / sp
            spy_invested += LOT * PICKS
        # mark equity for daily pnl series
        unreal = sum(LOT * ((px.get(l["sym"], l["entry"]) / l["entry"] - 1) *
                            (1 if l["side"] == "l" else -1))
                     for l in lots if not pd.isna(px.get(l["sym"])))
        equity = realized + unreal
        daily_pnl.append(equity - prev_equity)
        prev_equity = equity
    last_px = closes.loc[dates[-1]]
    unreal = sum(LOT * ((last_px.get(l["sym"], l["entry"]) / l["entry"] - 1) *
                        (1 if l["side"] == "l" else -1))
                 for l in lots if not pd.isna(last_px.get(l["sym"])))
    total = realized + unreal
    spy_pnl = spy_units * spy.loc[dates[-1]] - spy_invested if spy_invested else 0
    ret_pct = total / invested * 100 if invested else 0
    spy_pct = spy_pnl / spy_invested * 100 if spy_invested else 0
    ser = pd.Series(daily_pnl)
    sharpe = (ser.mean() / ser.std() * (252 ** 0.5)) if ser.std() else 0
    return {"pnl": round(total), "invested": round(invested), "ret_pct": round(ret_pct, 2),
            "spy_pct": round(spy_pct, 2), "alpha_pp": round(ret_pct - spy_pct, 2),
            "sharpe": round(float(sharpe), 2), "trades": int(invested // LOT)}


def random_config(rng: random.Random) -> dict:
    w = [rng.random() for _ in range(4)]
    t = sum(w)
    return {
        "w_r3": round(w[0] / t, 3), "w_r6": round(w[1] / t, 3),
        "w_ma50": round(w[2] / t, 3), "w_ma200": round(w[3] / t, 3),
        "mom_scale": rng.choice([80, 100, 130, 160]),
        "w_mom": rng.choice([0.5, 0.6, 0.7, 0.8]),
        "long_th": rng.choice([58, 62, 66, 70]),
        "short_th": rng.choice([30, 34, 38, 42]),
        "stop": rng.choice([-0.08, -0.10, -0.12, -0.15]),
        "target": rng.choice([0.15, 0.20, 0.25, 0.30]),
        "max_hold": rng.choice([20, 40, 60, 90]),
    }


LIVE_LIKE = {"w_r3": 0.4, "w_r6": 0.3, "w_ma50": 0.15, "w_ma200": 0.15,
             "mom_scale": 130, "w_mom": 0.6, "long_th": 63, "short_th": 38,
             "stop": -0.10, "target": 0.20, "max_hold": 60}


def main() -> None:
    n_iter = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    closes = load_closes()
    spy = closes["SPY"]
    universe = closes.drop(columns=["SPY"])
    start = universe.index[210]
    rng = random.Random(42)
    results = []
    print(f"Backtest lab: {universe.shape[1]} symbols, {len(universe)} days, {n_iter} iterations")

    def run(cfg, tag):
        t0 = time.time()
        sc = scores_matrix(universe, cfg)
        train = simulate(universe, sc, spy, cfg, start, TRAIN_END)
        test = simulate(universe, sc, spy, cfg, TRAIN_END, universe.index[-1])
        row = {"tag": tag, "config": cfg, "train": train, "test": test}
        results.append(row)
        print(f"[{tag}] train alpha {train['alpha_pp']:+.1f}pp (ret {train['ret_pct']:+.1f}% vs SPY {train['spy_pct']:+.1f}%)"
              f" | TEST alpha {test['alpha_pp']:+.1f}pp (ret {test['ret_pct']:+.1f}%)"
              f" | sharpe {train['sharpe']:.2f}/{test['sharpe']:.2f} | {time.time()-t0:.0f}s")
        OUT.write_text(json.dumps(results, indent=1), encoding="utf-8")

    run(LIVE_LIKE, "LIVE-LIKE baseline")
    for i in range(n_iter):
        run(random_config(rng), f"rand-{i+1:02d}")

    ranked = sorted(results[1:], key=lambda r: r["train"]["alpha_pp"], reverse=True)
    print("\n=== Top-5 by TRAIN alpha, with out-of-sample TEST check ===")
    for r in ranked[:5]:
        print(f"{r['tag']}: train {r['train']['alpha_pp']:+.1f}pp | TEST {r['test']['alpha_pp']:+.1f}pp | {r['config']}")
    base = results[0]
    print(f"\nBaseline (live-like): train {base['train']['alpha_pp']:+.1f}pp | TEST {base['test']['alpha_pp']:+.1f}pp")
    robust = [r for r in ranked if r["test"]["alpha_pp"] > base["test"]["alpha_pp"]
              and r["train"]["alpha_pp"] > base["train"]["alpha_pp"]]
    print(f"Configs beating baseline on BOTH windows: {len(robust)}")
    print("Results saved to", OUT)


if __name__ == "__main__":
    main()
