"""Round 4: trend filter with re-entry + vol-regime exits.

Trend: exit when price closes below MA{50,100,200} (optionally with a b% buffer
below the MA to cut whipsaw); re-enter when price reclaims the MA (optionally
b% above). Variants with the rebuy-below-sale constraint stacked on top.
Vol-regime: exit when 20d vol > k x its own 252d median {k=1.5,2.0,2.5};
re-enter when vol normalizes (< 1.25x median), with/without below-sale.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import common as C

OUT = Path(__file__).parent


def make_trend(ma, buf, below):
    def builder(p):
        m = p[ma]
        return {"exit_sig": p["px"] < m * (1 - buf),
                "enter_sig": p["px"] > m * (1 + buf),
                "rebuy_below_sale": below}
    return builder


def make_vol(k, below):
    def builder(p):
        return {"exit_sig": p["volratio"] > k,
                "enter_sig": p["volratio"] < 1.25,
                "rebuy_below_sale": below}
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    for ma in ("ma50", "ma100", "ma200"):
        if ma == "ma100":
            continue  # not precomputed; use 50/200
        for buf in (0.0, 0.02, 0.05):
            for below in (False, True):
                nm = f"trend {ma} buf{int(buf*100)}% {'below' if below else 'free'}"
                defs.append((nm, make_trend(ma, buf, below)))
    for k in (1.5, 2.0, 2.5):
        for below in (False, True):
            nm = f"vol>{k}x exit, <1.25x reenter {'below' if below else 'free'}"
            defs.append((nm, make_vol(k, below)))
    rows = C.run_strategies(preps, defs)
    rows = C.print_rows(rows, sort_by="valid")
    (OUT / "round4_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
