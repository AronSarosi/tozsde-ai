"""Round 1: overextension take-profit + pullback rebuy.

Sell when the stock is 'relatively high' vs its own 200d MA history:
  z200 > Z      (distance above MA in units of its own 252d std), or
  pct_dist > P  (distance-above-MA in top P of trailing 3y history).
Rebuy when:
  dropX  - price fell X% below the sale price
  toMA   - price back at/below its 200d MA
  zlow   - z200 < 0.5 (overextension gone)
Optionally give up after max_out days out and rebuy at market.
"""
import json
from pathlib import Path
import numpy as np
import common as C

OUT = Path(__file__).parent


def make(exit_kind, exit_thr, rebuy_kind, rebuy_thr, max_out):
    def builder(p):
        if exit_kind == "z":
            ex = p["z200"] > exit_thr
        else:
            ex = p["pct_dist"] > exit_thr
        kw = {"exit_sig": ex, "max_out": max_out}
        if rebuy_kind == "drop":
            kw["rebuy_drop"] = rebuy_thr
        elif rebuy_kind == "toMA":
            kw["enter_sig"] = p["px"] <= p["ma200"]
        elif rebuy_kind == "zlow":
            kw["enter_sig"] = p["z200"] < rebuy_thr
        return kw
    return builder


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    defs = []
    exits = [("z", 1.5), ("z", 2.0), ("z", 2.5), ("z", 3.0),
             ("pct", 0.95), ("pct", 0.98)]
    rebuys = [("drop", 0.05), ("drop", 0.10), ("drop", 0.15),
              ("toMA", None), ("zlow", 0.5)]
    for ek, et in exits:
        for rk, rt in rebuys:
            for mo in (None, 60):
                nm = f"sell {ek}>{et} | rebuy {rk}{'' if rt is None else rt} | maxout {mo}"
                defs.append((nm, make(ek, et, rk, rt, mo)))
    rows = C.run_strategies(preps, defs)
    rows = C.print_rows(rows, sort_by="valid")
    (OUT / "round1_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
