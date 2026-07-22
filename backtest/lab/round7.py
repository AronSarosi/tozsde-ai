"""Round 7: lookback sweeps (Aron directive - every constant is a parameter).

a) Overextension retry across MA lookbacks L in {50..500}:
   sell z_L > {2.5, 3.0}, rebuy {drop5%, below-sale}, sell_frac {1.0, 0.5}.
b) Percentile variant: sell pct_L > 0.98, rebuy drop5%, sf 1.0.
c) Trend-filter retry across long lookbacks L in {150..500}, buffer {0,5%},
   free re-entry on reclaim (its best round-4 shape).
d) Vol-regime retry: vol20 > {2.0,2.5} x median over {126,252,504}d, reenter
   <1.25x, free re-entry.
Windows: tune / valid / full10.
"""
import json
from pathlib import Path
import common as C

OUT = Path(__file__).parent


def make_z(L, thr, rebuy, sf):
    def builder(p):
        kw = {"exit_sig": p[f"z_{L}"] > thr, "sell_frac": sf}
        if rebuy == "drop5":
            kw["rebuy_drop"] = 0.05
        else:
            kw["rebuy_below_sale"] = True
        return kw
    return builder


def make_pct(L):
    def builder(p):
        return {"exit_sig": p[f"pct_{L}"] > 0.98, "rebuy_drop": 0.05}
    return builder


def make_trend(L, buf):
    def builder(p):
        m = p[f"ma_{L}"]
        return {"exit_sig": p["px"] < m * (1 - buf),
                "enter_sig": p["px"] > m * (1 + buf)}
    return builder


def make_vol(VL, k):
    def builder(p):
        return {"exit_sig": p[f"volratio_{VL}"] > k,
                "enter_sig": p[f"volratio_{VL}"] < 1.25}
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    for L in C.LOOKBACKS:
        for thr in (2.5, 3.0):
            for rebuy in ("drop5", "below"):
                for sf in (1.0, 0.5):
                    defs.append((f"z{L}>{thr} {rebuy} sf{sf}", make_z(L, thr, rebuy, sf)))
        defs.append((f"pct{L}>0.98 drop5", make_pct(L)))
    for L in (150, 200, 250, 300, 400, 500):
        for buf in (0.0, 0.05):
            defs.append((f"trend ma{L} buf{int(buf*100)}", make_trend(L, buf)))
    for VL in (126, 252, 504):
        for k in (2.0, 2.5):
            defs.append((f"vol{VL} >{k}x", make_vol(VL, k)))
    rows = C.run_strategies(preps, defs, windows=("tune", "valid", "full10"))
    rows = C.print_rows(rows, windows=("tune", "valid", "full10"), sort_by="valid")
    (OUT / "round7_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
