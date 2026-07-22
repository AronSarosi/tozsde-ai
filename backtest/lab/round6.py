"""Round 6: cap the runaway failure mode + fine sweep of the robust region.

New engine feature giveup_up: while waiting to rebuy lower, if price instead
breaks +X% ABOVE the sale price, admit wrong and chase back in. This caps the
worst case (missing a 10x) at roughly X pp per event.

Sweep: trail {20,22,25,28,32} x sell_frac {1.0,0.5} x giveup_up {None,20%,30%,50%}
all with rebuy-below-sale, never give up on time. Windows: tune/valid/full10.
"""
import json
from pathlib import Path
import common as C

OUT = Path(__file__).parent


def make(trail, sf, gup):
    def builder(p):
        return {"trail_stop": trail, "sell_frac": sf,
                "rebuy_below_sale": True, "giveup_up": gup}
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    for t in (0.20, 0.22, 0.25, 0.28, 0.32):
        for sf in (1.0, 0.5):
            for gup in (None, 0.20, 0.30, 0.50):
                nm = f"trail{int(t*100)} sf{sf} gup{gup}"
                defs.append((nm, make(t, sf, gup)))
    rows = C.run_strategies(preps, defs, windows=("tune", "valid", "full10"))
    rows = C.print_rows(rows, windows=("tune", "valid", "full10"), sort_by="valid")
    (OUT / "round6_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
