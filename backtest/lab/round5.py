"""Round 5: partial profit-taking, combos, and robustness around the winner.

a) Robustness sweep of the round-2 winner: trail T in {12..30}, rebuy-below-sale,
   never give up, full and half (sell_frac 0.5) exits.
b) Rebuy discount variants: require 2%/5% below sale instead of any tick below.
c) Combo exits: trailing-stop OR overextension (z>3) / OR RSI>80, rebuy below.
d) Partial version of the round-1 conservative cell (z>3, rebuy drop5).
"""
import json
from pathlib import Path
import numpy as np
import common as C

OUT = Path(__file__).parent


def make(trail=None, sf=1.0, rebuy_drop=None, extra=None, extra_thr=None):
    def builder(p):
        kw = {"sell_frac": sf}
        if trail is not None:
            kw["trail_stop"] = trail
        if rebuy_drop is not None:
            kw["rebuy_drop"] = rebuy_drop
        else:
            kw["rebuy_below_sale"] = True
        if extra == "z":
            kw["exit_sig"] = p["z200"] > extra_thr
        elif extra == "rsi":
            kw["exit_sig"] = p["rsi"] > extra_thr
        return kw
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    # a) robustness sweep, full + half exits
    for t in (0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30):
        for sf in (1.0, 0.5):
            defs.append((f"trail{int(t*100)} below sf{sf}", make(trail=t, sf=sf)))
    # b) rebuy discount variants on trail20
    for rd in (0.02, 0.05, 0.08):
        defs.append((f"trail20 rebuy drop{rd} sf1.0", make(trail=0.20, rebuy_drop=rd)))
    # c) combo exits
    for t in (0.20, 0.25):
        for ex, thr in (("z", 3.0), ("rsi", 80)):
            for sf in (1.0, 0.5):
                defs.append((f"trail{int(t*100)} OR {ex}>{thr} below sf{sf}",
                             make(trail=t, sf=sf, extra=ex, extra_thr=thr)))
    # d) overextension-only partial: z>3 sell half, rebuy drop5
    defs.append(("z>3 drop0.05 sf0.5", make(sf=0.5, rebuy_drop=0.05, extra="z", extra_thr=3.0)))
    defs.append(("z>3 below sf0.5", make(sf=0.5, extra="z", extra_thr=3.0)))
    defs.append(("rsi>80 below sf0.5", make(sf=0.5, extra="rsi", extra_thr=80)))
    rows = C.run_strategies(preps, defs, windows=("tune", "valid", "full10"))
    rows = C.print_rows(rows, windows=("tune", "valid", "full10"), sort_by="valid")
    (OUT / "round5_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
