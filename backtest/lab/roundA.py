"""Round A - the discount cliff.

Question: prior lab showed rebuy-any-tick-below-sale works (+1pp/yr) and
rebuy-5..15%-below is catastrophic. Where between 0 and 5% does it break?

Grid: sell triggers = the 4 proven exits (z50>2.5, z150>3, trail25, RSI>80),
rebuy at sale*(1-d) for d in {0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5}% (d=0 = strict
any-tick-below). Full exits, no fallbacks. Windows: tune / valid / full10.
Logs median wait-to-rebuy days and % of exits never refilled.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from common2 import (load, build_preps, augment, run2, print2, exit_z,
                     exit_rsi)

mat = load()
preps = build_preps(mat)
augment(preps, mat)
print(f"{len(preps)} symbols")

TRIGGERS = [
    ("z50>2.5",  lambda p: exit_z(p, 50, 2.5)),
    ("z150>3",   lambda p: exit_z(p, 150, 3.0)),
    ("trail25",  None),
    ("rsi80",    lambda p: exit_rsi(p, 80)),
]
DISCOUNTS = [0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]

defs = []
for tname, sig in TRIGGERS:
    for d in DISCOUNTS:
        def builder(p, sig=sig, d=d, tname=tname):
            kw = {"tranches": ((1.0, "below", d),)}
            if tname == "trail25":
                kw["trail_stop"] = 0.25
            else:
                kw["exit_sig"] = sig(p)
            return kw
        defs.append((f"{tname} rebuy-{d*100:.1f}%", builder))

wins = ("tune", "valid", "full10")
rows = run2(preps, defs, windows=wins)
rows = print2(rows, windows=wins, sort_by="valid")
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
