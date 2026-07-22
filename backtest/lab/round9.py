"""Round 9: TSLA deep dive + winner trade traces.

a) Score a wide rule set on TSLA alone (tune/valid/full5/full10 edges).
b) Print the full trade log of the best TSLA rules and of the overall winner
   (trail25 below sf1.0) on TSLA and NVDA - sanity check the mechanics.
"""
import json
from pathlib import Path
import numpy as np
import common as C

OUT = Path(__file__).parent


def trail(t, sf):
    return {"trail_stop": t, "rebuy_below_sale": True, "sell_frac": sf}


def zx(p, L, thr, sf):
    return {"exit_sig": p[f"z_{L}"] > thr, "rebuy_below_sale": True, "sell_frac": sf}


def rsi(p, hi, sf):
    return {"exit_sig": p["rsi"] > hi, "rebuy_below_sale": True, "sell_frac": sf}


def trace(p, win, **kw):
    """Replicates common.sim but records trades."""
    sl = C.window_slice(p, C.WINDOWS[win])
    a, b = sl
    px, dates = p["px"][a:b], p["dates"][a:b]
    for k in ("exit_sig", "enter_sig"):
        if kw.get(k) is not None:
            kw[k] = kw[k][a:b]
    exit_sig = kw.get("exit_sig")
    trail_stop = kw.get("trail_stop")
    sf = kw.get("sell_frac", 1.0)
    below = kw.get("rebuy_below_sale", False)
    n = len(px)
    V, f = 1.0 - C.COST, 1.0
    entry = peak = px[0]
    sale = np.nan
    can_sell = True
    trades = []
    for i in range(1, n):
        V *= 1.0 + f * (px[i] / px[i - 1] - 1.0)
        sold = False
        if f > 0 and can_sell:
            do = bool(exit_sig[i]) if exit_sig is not None else False
            if px[i] > peak:
                peak = px[i]
            if trail_stop is not None and px[i] <= peak * (1 - trail_stop):
                do = True
            if do:
                V -= V * f * sf * C.COST
                f *= 1 - sf
                sale = px[i]
                can_sell = False
                sold = True
                trades.append(("SELL", dates[i], round(px[i], 2)))
        if f < 1 and not sold:
            ok = True
            if below:
                ok = px[i] < sale
            if ok:
                V -= V * (1 - f) * C.COST
                f = 1.0
                entry = peak = px[i]
                can_sell = True
                trades.append(("BUY ", dates[i], round(px[i], 2)))
    bh = (1 - C.COST) * px[-1] / px[0] - 1
    return trades, (V - 1) * 100, bh * 100


def main():
    mat = C.load()
    p = C.prep(mat["TSLA"])
    pn = C.prep(mat["NVDA"])
    rules = []
    for t in (0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.32):
        for sf in (1.0, 0.5):
            rules.append((f"trail{int(t*100)} sf{sf}", trail(t, sf)))
    for L in C.LOOKBACKS:
        for thr in (2.5, 3.0):
            for sf in (1.0, 0.5):
                rules.append((f"z{L}>{thr} sf{sf}", zx(p, L, thr, sf)))
    for hi in (75, 80):
        rules.append((f"rsi{hi} sf1.0", rsi(p, hi, 1.0)))
    print("TSLA edges (pp) per window:")
    scored = []
    for nm, kw in rules:
        row = {"name": nm}
        for w in ("tune", "valid", "full5", "full10"):
            sl = C.window_slice(p, C.WINDOWS[w])
            a, b = sl
            kw2 = {k: (v[a:b] if k in ("exit_sig", "enter_sig") and v is not None else v)
                   for k, v in kw.items()}
            r = C.sim(p["px"][a:b], **kw2)
            row[w] = round(r["edge"], 1)
            row[w + "_sells"] = r["n_sells"]
        scored.append(row)
    scored.sort(key=lambda r: min(r["tune"], r["valid"]), reverse=True)
    for r in scored[:18]:
        print(f"  {r['name']:18s} tune {r['tune']:+8.1f}  valid {r['valid']:+8.1f}  "
              f"full5 {r['full5']:+8.1f}  full10 {r['full10']:+9.1f}  sells(v) {r['valid_sells']}")
    (OUT / "round9_tsla.json").write_text(json.dumps(scored, indent=1), encoding="utf-8")

    print("\nTrade log: trail25 below sf1.0 on TSLA, full5")
    tr, s, bh = trace(p, "full5", **trail(0.25, 1.0))
    print(f"  strat {s:+.1f}% vs bh {bh:+.1f}%")
    for t in tr:
        print("  ", *t)
    print("\nTrade log: best-z rule z50>2.5 sf1.0 on TSLA, full5")
    tr, s, bh = trace(p, "full5", **zx(p, 50, 2.5, 1.0))
    print(f"  strat {s:+.1f}% vs bh {bh:+.1f}%")
    for t in tr:
        print("  ", *t)
    print("\nTrade log: trail25 below sf1.0 on NVDA, full5")
    tr, s, bh = trace(pn, "full5", **trail(0.25, 1.0))
    print(f"  strat {s:+.1f}% vs bh {bh:+.1f}%")
    for t in tr:
        print("  ", *t)


if __name__ == "__main__":
    main()
