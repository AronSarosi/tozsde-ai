"""Shared machinery for the beat-buy-and-hold lab.

Windows (walk-forward honesty):
  TUNE  = 2021-07-01 .. 2023-12-31   (parameter selection)
  VALID = 2024-01-01 .. 2026-07-21   (out-of-sample confirmation)
  FULL5 = 2021-07-01 .. 2026-07-21
  FULL10= all history (~2016-07 ..)

Costs: 0.1% per side on every traded notional. Buy-and-hold pays the same
one-off 0.1% entry cost, so a strategy that never trades nets exactly B&H.

Every strategy starts INVESTED on day 1 of the window (same capital
deployment as B&H). The game is purely: when do you step out and when do
you step back in. This kills the degenerate "wait forever then match B&H"
case from earlier grids - here doing nothing IS B&H, and edge comes only
from round trips. We log n_sells and avg days spent out per round trip.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "tozsde_ai.db"
TUNE = ("2021-07-01", "2023-12-31")
VALID = ("2024-01-01", "2026-12-31")
FULL5 = ("2021-07-01", "2026-12-31")
FULL10 = ("2016-01-01", "2026-12-31")
WINDOWS = {"tune": TUNE, "valid": VALID, "full5": FULL5, "full10": FULL10,
           # 6y window, proportional 3y/3y split
           "tune6": ("2020-07-01", "2023-06-30"),
           "valid6": ("2023-07-01", "2026-12-31"),
           # 7y window, proportional 3.5y/3.5y split
           "tune7": ("2019-07-01", "2023-01-31"),
           "valid7": ("2023-02-01", "2026-12-31")}
LOOKBACKS = (50, 100, 150, 200, 250, 300, 400, 500)
KEY = ["TSLA", "NVDA", "AMZN", "INTC"]
COST = 0.001


def load() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT symbol, date, close FROM prices_daily", con)
    con.close()
    return df.pivot(index="date", columns="symbol", values="close").sort_index()


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _roll_pctile(x: np.ndarray, win: int) -> np.ndarray:
    """Percentile rank of x[i] within trailing `win` observations (incl. self)."""
    out = np.full(len(x), np.nan)
    if len(x) < win:
        return out
    sw = np.lib.stride_tricks.sliding_window_view(x, win)
    out[win - 1:] = (sw <= sw[:, -1:]).mean(axis=1)
    return out


def prep(c: pd.Series) -> dict:
    """c: dropna'd close series for one symbol. Returns dict of numpy arrays."""
    c = c.dropna()
    r1 = c.pct_change()
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    ma200 = c.rolling(200).mean()
    dist200 = c / ma200 - 1
    z200 = dist200 / dist200.rolling(252).std()
    hi252 = c.rolling(252).max()
    vol20 = r1.rolling(20).std()
    volmed = vol20.rolling(252).median()
    d = {
        "dates": c.index.to_numpy(),
        "px": c.to_numpy(float),
        "ret1": r1.to_numpy(float),
        "ma20": ma20.to_numpy(float),
        "ma50": ma50.to_numpy(float),
        "ma200": ma200.to_numpy(float),
        "dist200": dist200.to_numpy(float),
        "z200": z200.to_numpy(float),
        "pct_dist": _roll_pctile(dist200.to_numpy(float), 756),
        "rsi": _rsi(c).to_numpy(float),
        "hi252": hi252.to_numpy(float),
        "dd252": (c / hi252 - 1).to_numpy(float),
        "vol20": vol20.to_numpy(float),
        "volratio": (vol20 / volmed).to_numpy(float),
        "above200": (c > ma200).to_numpy(bool),
        "above50": (c > ma50).to_numpy(bool),
        "above20": (c > ma20).to_numpy(bool),
    }
    # lookback sweep: MA distance, z-score and 3y percentile per lookback
    for L in LOOKBACKS:
        maL = c.rolling(L).mean()
        distL = c / maL - 1
        d[f"ma_{L}"] = maL.to_numpy(float)
        d[f"dist_{L}"] = distL.to_numpy(float)
        d[f"z_{L}"] = (distL / distL.rolling(252).std()).to_numpy(float)
        d[f"pct_{L}"] = _roll_pctile(distL.to_numpy(float), 756)
    # vol-regime with swept median lookbacks
    for VL in (126, 252, 504):
        d[f"volratio_{VL}"] = (vol20 / vol20.rolling(VL).median()).to_numpy(float)
    return d


def sim(px: np.ndarray, *, exit_sig=None, enter_sig=None, trail_stop=None,
        trail_min_gain=None, profit_take=None, rebuy_drop=None,
        rebuy_below_sale=False, max_out=None, giveup_up=None,
        sell_frac=1.0, cost=COST):
    """Event loop over one window. Arrays already sliced to the window.

    Start fully invested at px[0] (entry cost applied). Exit rules:
      exit_sig[i] True, OR px >= entry*(1+profit_take), OR trailing stop
      (px <= peak*(1-trail_stop), optionally only after peak >= entry*(1+trail_min_gain)).
    Sell `sell_frac` of the invested fraction; only one sell per round trip.
    Re-entry (back to fully invested) when enter_sig[i] (default True) AND
    price constraint (rebuy_drop: px <= sale*(1-rebuy_drop);
    rebuy_below_sale: px < sale). max_out: after that many days out, force
    re-entry regardless (give-up). Same-day sell+rebuy disallowed.
    """
    n = len(px)
    V = 1.0 - cost           # initial buy
    f = 1.0
    entry = peak = px[0]
    sale = np.nan
    can_sell = True
    n_sells = n_buys = 0
    days_out_cur = 0
    out_days_total = 0
    f_sum = 1.0
    for i in range(1, n):
        r = px[i] / px[i - 1] - 1.0
        V *= 1.0 + f * r
        sold_today = False
        if f > 0 and can_sell:
            do_exit = False
            if exit_sig is not None and exit_sig[i]:
                do_exit = True
            if profit_take is not None and px[i] >= entry * (1 + profit_take):
                do_exit = True
            if px[i] > peak:
                peak = px[i]
            if trail_stop is not None and px[i] <= peak * (1 - trail_stop):
                if trail_min_gain is None or peak >= entry * (1 + trail_min_gain):
                    do_exit = True
            if do_exit:
                traded = V * f * sell_frac
                V -= traded * cost
                f *= 1.0 - sell_frac
                sale = px[i]
                can_sell = False
                n_sells += 1
                days_out_cur = 0
                sold_today = True
        elif f > 0 and px[i] > peak:
            peak = px[i]
        if f < 1.0 and not sold_today:
            ok = True if enter_sig is None else bool(enter_sig[i])
            if rebuy_drop is not None:
                ok = ok and px[i] <= sale * (1 - rebuy_drop)
            elif rebuy_below_sale:
                ok = ok and px[i] < sale
            if max_out is not None and days_out_cur >= max_out:
                ok = True
            if giveup_up is not None and px[i] >= sale * (1 + giveup_up):
                ok = True  # runaway: admit wrong, chase back in
            if ok:
                traded = V * (1.0 - f)
                V -= traded * cost
                f = 1.0
                entry = peak = px[i]
                can_sell = True
                n_buys += 1
            else:
                days_out_cur += 1
                out_days_total += 1 if f == 0 else 0
        f_sum += f
    bh = (1.0 - cost) * px[-1] / px[0] - 1.0
    strat = V - 1.0
    return {
        "strat": strat * 100, "bh": bh * 100, "edge": (strat - bh) * 100,
        "n_sells": n_sells, "n_buys": n_buys,
        "time_in": 100 * f_sum / n,
        "avg_out": out_days_total / n_sells if n_sells else 0.0,
    }


def window_slice(prepd: dict, win: tuple[str, str], min_days: int = 200):
    dates = prepd["dates"]
    m = (dates >= win[0]) & (dates <= win[1])
    if m.sum() < min_days:
        return None
    idx = np.where(m)[0]
    return idx[0], idx[-1] + 1


def run_strategies(preps: dict, strat_defs, windows=("tune", "valid"),
                   min_days: int = 200):
    """strat_defs: list of (name, builder). builder(prepd) -> dict of sim
    kwargs where any exit_sig/enter_sig are FULL-HISTORY arrays (sliced here).
    Returns rows: {name, per-window aggregate stats}.
    """
    rows = []
    for name, builder in strat_defs:
        row = {"name": name}
        for wname in windows:
            win = WINDOWS[wname]
            per = {}
            for s, p in preps.items():
                sl = window_slice(p, win, min_days)
                if sl is None:
                    continue
                a, b = sl
                kw = builder(p)
                kw2 = {}
                for k, v in kw.items():
                    if k in ("exit_sig", "enter_sig") and v is not None:
                        kw2[k] = v[a:b]
                    else:
                        kw2[k] = v
                per[s] = sim(p["px"][a:b], **kw2)
            e = pd.Series({k: v["edge"] for k, v in per.items()})
            e_agg = e.drop(index="SPY", errors="ignore")
            row[wname] = {
                "med_edge": round(float(e_agg.median()), 2),
                "pos_pct": round(100 * float((e_agg > 0).mean()), 1),
                "med_sells": round(float(np.median([v["n_sells"] for k, v in per.items() if k != "SPY"])), 1),
                "med_tim": round(float(np.median([v["time_in"] for k, v in per.items() if k != "SPY"])), 1),
                "med_avg_out": round(float(np.median([v["avg_out"] for k, v in per.items() if k != "SPY"])), 1),
                **{k: (round(per[k]["edge"], 1) if k in per else None) for k in KEY},
            }
        rows.append(row)
    return rows


def print_rows(rows, windows=("tune", "valid"), sort_by="valid", top=None):
    rows = sorted(rows, key=lambda r: r[sort_by]["med_edge"], reverse=True)
    hdr = "name".ljust(52) + "".join(
        f"| {w}: medE  pos%  sells  tim%  " for w in windows) + "| TSLA/NVDA/AMZN/INTC (valid)"
    print(hdr)
    print("-" * len(hdr))
    for r in (rows[:top] if top else rows):
        line = r["name"][:52].ljust(52)
        for w in windows:
            d = r[w]
            line += f"| {d['med_edge']:+7.2f} {d['pos_pct']:5.1f} {d['med_sells']:5.1f} {d['med_tim']:5.1f} "
        v = r[windows[-1]]
        line += f"| {v['TSLA']}/{v['NVDA']}/{v['AMZN']}/{v['INTC']}"
        print(line)
    return rows


def build_preps(mat: pd.DataFrame, min_obs: int = 300) -> dict:
    return {s: prep(mat[s]) for s in mat.columns if mat[s].dropna().size >= min_obs}
