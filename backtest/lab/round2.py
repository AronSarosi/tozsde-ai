"""Round 2: trailing-high take-profit with rebuy-lower-only constraint.

Exit: trailing stop - price falls T% from its running peak since entry,
optionally only armed after the peak is at least G% above entry (so it is a
profit-protector, not a plain stop-loss). Also plain profit targets.
Re-entry: only below the sale price (strict), or drop X% below sale;
give-up after max_out days {None, 10, 30, 90} then rebuy at market.
"""
import json
from pathlib import Path
import common as C

OUT = Path(__file__).parent


def make(trail, gain, rebuy_kind, rebuy_thr, max_out, pt=None):
    def builder(p):
        kw = {"max_out": max_out}
        if trail is not None:
            kw["trail_stop"] = trail
            kw["trail_min_gain"] = gain
        if pt is not None:
            kw["profit_take"] = pt
        if rebuy_kind == "below":
            kw["rebuy_below_sale"] = True
        elif rebuy_kind == "drop":
            kw["rebuy_drop"] = rebuy_thr
        return kw
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    for trail in (0.10, 0.15, 0.20, 0.25):
        for gain in (None, 0.25, 0.50):
            for rk, rt in (("below", None), ("drop", 0.05)):
                for mo in (None, 10, 30, 90):
                    nm = (f"trail{int(trail*100)} gain{gain} | "
                          f"rebuy {rk}{'' if rt is None else rt} | maxout {mo}")
                    defs.append((nm, make(trail, gain, rk, rt, mo)))
    # plain profit-target take-profits
    for pt in (0.30, 0.50, 1.00):
        for rk, rt in (("below", None), ("drop", 0.05), ("drop", 0.10)):
            for mo in (None, 30):
                nm = f"PT{int(pt*100)} | rebuy {rk}{'' if rt is None else rt} | maxout {mo}"
                defs.append((nm, make(None, None, rk, rt, mo, pt=pt)))
    rows = C.run_strategies(preps, defs)
    rows = C.print_rows(rows, sort_by="valid")
    (OUT / "round2_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
