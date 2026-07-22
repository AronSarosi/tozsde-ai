"""Round-2 lab engine: flexible RE-ENTRY rules on top of the proven
"sell at extreme strength" exits.

Extends common.py with:
  - prep2(): extra arrays (close-based ATR%, sigma20, 10d low, calm days,
    RSI thresholds, MA touches) for re-entry conditions.
  - sim2(): tranche-based rebuy engine. A sell splits the sold amount into
    tranches; each tranche refills independently by its own rule:
      ("below", d)   px < sale (d=0, strict) or px <= sale*(1-d)
      ("atr", k)     px <= sale*(1 - k*atrp14_at_sale)   (vol-scaled discount)
      ("sigma", k)   px <= sale*(1 - k*sigma20_at_sale)
      ("cond", name) px < sale AND cond arrays[name][i]  (conditional re-entry)
      ("decay", (d0, T))  px <= sale*(1 - d0*max(0, 1 - t/T)); after T days the
                     demand decays to "any tick strictly below sale" - caps the
                     never-rebought tail by construction
      ("bounce", (b, cap)) px >= low_since_sale*(1+b) (confirmed bounce);
                     cap=True additionally requires px < sale
      ("any", None)  refill immediately next day (control)
    Global fallbacks fill ALL pending tranches: max_out days since sale,
    giveup_up (px >= sale*(1+x) runaway chase).
  - Stats: per-fill wait days, % of tranche-instances never refilled by
    window end, achieved rebuy discount vs sale.

Costs 0.1%/side; start fully invested day 1 (zero trades = exactly B&H).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from common import (ROOT, DB, TUNE, VALID, FULL5, FULL10, WINDOWS, KEY, COST,
                    load, prep, build_preps, window_slice, _rsi)


def augment(preps: dict, mat: pd.DataFrame) -> None:
    """Add re-entry arrays to each prep dict (aligned to its dropna'd close)."""
    for s, p in preps.items():
        c = mat[s].dropna()
        r1 = c.pct_change()
        # close-based ATR proxy: 14d mean of |pct change| (no OHLC in DB)
        atrp14 = r1.abs().rolling(14).mean()
        sigma20 = r1.rolling(20).std()
        lo10 = c.rolling(10).min()
        lo20 = c.rolling(20).min()
        # calm day: |ret| < 1x its own 20d sigma; calm3 = 3 in a row
        calm = (r1.abs() < sigma20).astype(float)
        calm3 = calm.rolling(3).sum() >= 3
        p["atrp14"] = atrp14.to_numpy(float)
        p["sigma20"] = sigma20.to_numpy(float)
        p["is_lo10"] = (c <= lo10).to_numpy(bool)
        p["is_lo20"] = (c <= lo20).to_numpy(bool)
        p["calm3"] = calm3.to_numpy(bool)
        p["touch_ma20"] = (c <= c.rolling(20).mean()).to_numpy(bool)
        p["touch_ma50"] = (c <= c.rolling(50).mean()).to_numpy(bool)
        p["rsi_lt_40"] = (p["rsi"] < 40)
        p["rsi_lt_45"] = (p["rsi"] < 45)
        p["rsi_lt_50"] = (p["rsi"] < 50)
        p["rsi_lt_55"] = (p["rsi"] < 55)
        p["rsi_lt_60"] = (p["rsi"] < 60)


def sim2(px: np.ndarray, arrs: dict, *, exit_sig=None, trail_stop=None,
         sell_frac=1.0, tranches=(((1.0, "below", 0.0)),), max_out=None,
         giveup_up=None, cost=COST):
    """Event loop over one window. px and every array in arrs already sliced.

    tranches: sequence of (weight, mode, param); weights sum to 1. On a sell,
    the sold exposure S is split by weight; tranche j refills when its rule
    fires (see module docstring). A new sell is allowed only when ALL tranches
    have refilled (position back to full). Fallbacks (max_out / giveup_up)
    fill every pending tranche at once.
    """
    n = len(px)
    V = 1.0 - cost
    f = 1.0                      # invested fraction of wealth-relative exposure
    entry = peak = px[0]
    can_sell = True
    sale = np.nan
    sale_i = -1
    low_since = np.nan
    atr_at_sale = sig_at_sale = np.nan
    pending = []                 # list of [exposure, mode, param]
    n_sells = 0
    n_fills = 0
    waits = []                   # days from sale to each tranche fill
    discounts = []               # (sale - fill)/sale per fill
    tranche_total = 0
    f_sum = 1.0
    exit_arr = arrs.get("exit_sig") if exit_sig is None else exit_sig
    for i in range(1, n):
        r = px[i] / px[i - 1] - 1.0
        V *= 1.0 + f * r
        sold_today = False
        if can_sell:
            do_exit = False
            if exit_arr is not None and exit_arr[i]:
                do_exit = True
            if px[i] > peak:
                peak = px[i]
            if trail_stop is not None and px[i] <= peak * (1 - trail_stop):
                do_exit = True
            if do_exit:
                S = f * sell_frac
                V -= V * S * cost
                f -= S
                sale = px[i]
                sale_i = i
                low_since = px[i]
                atr_at_sale = arrs["atrp14"][i]
                sig_at_sale = arrs["sigma20"][i]
                can_sell = False
                n_sells += 1
                pending = [[S * w, m, prm] for (w, m, prm) in tranches]
                tranche_total += len(pending)
                sold_today = True
        if pending and not sold_today:
            if px[i] < low_since:
                low_since = px[i]
            force = False
            if max_out is not None and (i - sale_i) >= max_out:
                force = True
            if giveup_up is not None and px[i] >= sale * (1 + giveup_up):
                force = True
            still = []
            for tr in pending:
                S, m, prm = tr
                fill = force
                if not fill:
                    if m == "below":
                        fill = px[i] < sale if prm == 0.0 else px[i] <= sale * (1 - prm)
                    elif m == "atr":
                        d = prm * atr_at_sale
                        fill = px[i] <= sale * (1 - d) if np.isfinite(d) else px[i] < sale
                    elif m == "sigma":
                        d = prm * sig_at_sale
                        fill = px[i] <= sale * (1 - d) if np.isfinite(d) else px[i] < sale
                    elif m == "cond":
                        fill = (px[i] < sale) and bool(arrs[prm][i])
                    elif m == "decay":
                        d0, T = prm
                        d = d0 * max(0.0, 1.0 - (i - sale_i) / T)
                        fill = px[i] < sale if d <= 0 else px[i] <= sale * (1 - d)
                    elif m == "bounce":
                        b, capped = prm
                        fill = px[i] >= low_since * (1 + b)
                        if capped:
                            fill = fill and px[i] < sale
                    elif m == "condonly":
                        fill = bool(arrs[prm][i])
                    elif m == "any":
                        fill = True
                if fill:
                    V -= V * S * cost
                    f += S
                    n_fills += 1
                    waits.append(i - sale_i)
                    discounts.append(1.0 - px[i] / sale)
                else:
                    still.append(tr)
            pending = still
            if not pending:
                entry = peak = px[i]
                can_sell = True
        f_sum += f
    bh = (1.0 - cost) * px[-1] / px[0] - 1.0
    strat = V - 1.0
    return {
        "strat": strat * 100, "bh": bh * 100, "edge": (strat - bh) * 100,
        "n_sells": n_sells, "n_fills": n_fills,
        "n_unfilled": len(pending),
        "n_tranches": tranche_total,
        "time_in": 100 * f_sum / n,
        "med_wait": float(np.median(waits)) if waits else np.nan,
        "med_disc": 100 * float(np.median(discounts)) if discounts else np.nan,
    }


ARR_KEYS = ("atrp14", "sigma20", "is_lo10", "is_lo20", "calm3", "touch_ma20",
            "touch_ma50", "rsi_lt_40", "rsi_lt_45", "rsi_lt_50", "rsi_lt_55",
            "rsi_lt_60")


def run2(preps: dict, strat_defs, windows=("tune", "valid"), min_days=200):
    """strat_defs: list of (name, builder). builder(prepd) -> dict with keys
    accepted by sim2; exit_sig is a FULL-HISTORY bool array (sliced here).
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
                kw = dict(builder(p))
                es = kw.pop("exit_sig", None)
                arrs = {k: p[k][a:b] for k in ARR_KEYS}
                if es is not None:
                    arrs["exit_sig"] = es[a:b]
                per[s] = sim2(p["px"][a:b], arrs, **kw)
            e = pd.Series({k: v["edge"] for k, v in per.items()})
            e_agg = e.drop(index="SPY", errors="ignore")
            npS = {k: v for k, v in per.items() if k != "SPY"}
            tot_tr = sum(v["n_tranches"] for v in npS.values())
            tot_unf = sum(v["n_unfilled"] for v in npS.values())
            waits = [v["med_wait"] for v in npS.values() if np.isfinite(v["med_wait"])]
            discs = [v["med_disc"] for v in npS.values() if np.isfinite(v["med_disc"])]
            row[wname] = {
                "med_edge": round(float(e_agg.median()), 2),
                "pos_pct": round(100 * float((e_agg > 0).mean()), 1),
                "med_sells": round(float(np.median([v["n_sells"] for v in npS.values()])), 1),
                "med_tim": round(float(np.median([v["time_in"] for v in npS.values()])), 1),
                "med_wait": round(float(np.median(waits)), 1) if waits else np.nan,
                "med_disc": round(float(np.median(discs)), 2) if discs else np.nan,
                "never_pct": round(100 * tot_unf / tot_tr, 1) if tot_tr else 0.0,
                **{k: (round(per[k]["edge"], 1) if k in per else None) for k in KEY},
            }
        rows.append(row)
    return rows


def print2(rows, windows=("tune", "valid"), sort_by="valid", top=None):
    rows = sorted(rows, key=lambda r: r[sort_by]["med_edge"], reverse=True)
    hdr = ("name".ljust(46)
           + "".join(f"| {w[:6]}: medE  pos%  wait nofil " for w in windows)
           + "| T/N/A/I (last w)")
    print(hdr)
    print("-" * len(hdr))
    for r in (rows[:top] if top else rows):
        line = r["name"][:46].ljust(46)
        for w in windows:
            d = r[w]
            mw = f"{d['med_wait']:5.1f}" if np.isfinite(d.get("med_wait", np.nan)) else "    -"
            line += f"| {d['med_edge']:+7.2f} {d['pos_pct']:5.1f} {mw} {d['never_pct']:5.1f} "
        v = r[windows[-1]]
        line += f"| {v['TSLA']}/{v['NVDA']}/{v['AMZN']}/{v['INTC']}"
        print(line)
    return rows


def exit_z(p, L, thr):
    z = p[f"z_{L}"]
    return np.nan_to_num(z, nan=-9) > thr


def exit_rsi(p, thr):
    return p["rsi"] > thr
