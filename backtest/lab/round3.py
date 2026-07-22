"""Round 3: RSI(14) overlays.

Exit: RSI > {70,75,80,85}.
Re-entry: RSI < {40,50,60}, or rebuy-below-sale, or drop 5% - with and without
the rebuy-lower-only constraint stacked on the RSI re-entry.
Also: RSI exit combined with the round-2 winner's trailing exit is deferred to
the combo round; here we isolate the oscillator.
"""
import json
from pathlib import Path
import common as C

OUT = Path(__file__).parent


def make(rsi_hi, rebuy_kind, rebuy_thr, max_out, below=False):
    def builder(p):
        kw = {"exit_sig": p["rsi"] > rsi_hi, "max_out": max_out,
              "rebuy_below_sale": below}
        if rebuy_kind == "rsi":
            kw["enter_sig"] = p["rsi"] < rebuy_thr
        elif rebuy_kind == "drop":
            kw["rebuy_drop"] = rebuy_thr
            kw["rebuy_below_sale"] = False
        elif rebuy_kind == "below":
            kw["rebuy_below_sale"] = True
        return kw
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    for hi in (70, 75, 80, 85):
        for rk, rt, below in (("rsi", 40, False), ("rsi", 50, False), ("rsi", 60, False),
                              ("rsi", 50, True), ("rsi", 60, True),
                              ("below", None, True), ("drop", 0.05, False)):
            for mo in (None, 30, 90):
                nm = (f"RSI>{hi} | rebuy {rk}{'' if rt is None else rt}"
                      f"{'+below' if below and rk == 'rsi' else ''} | maxout {mo}")
                defs.append((nm, make(hi, rk, rt, mo, below)))
    rows = C.run_strategies(preps, defs)
    rows = C.print_rows(rows, sort_by="valid")
    (OUT / "round3_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
