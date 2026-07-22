"""Round B - volatility-scaled rebuy discounts.

A fixed 2% means nothing for TSLA and a lot for KO. Rebuy at
sale*(1 - k*ATRp14_at_sale) or sale*(1 - k*sigma20_at_sale), k in
{0.25,0.5,0.75,1,1.5,2,3}. ATRp14 = 14d mean |daily pct change| (close-based,
no OHLC in DB); sigma20 = 20d std of daily returns. Both frozen at the sale
day. Triggers: z50>2.5, z150>3, trail25. Windows tune/valid/full10.
Reference rows: rebuy-0% (any tick) and rebuy-1.5% fixed.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common2 import load, build_preps, augment, run2, print2, exit_z

mat = load()
preps = build_preps(mat)
augment(preps, mat)
print(f"{len(preps)} symbols")

TRIGGERS = [
    ("z50>2.5", lambda p: exit_z(p, 50, 2.5)),
    ("z150>3",  lambda p: exit_z(p, 150, 3.0)),
    ("trail25", None),
]
KS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

defs = []
for tname, sig in TRIGGERS:
    for mode in ("atr", "sigma"):
        for k in KS:
            def builder(p, sig=sig, mode=mode, k=k, tname=tname):
                kw = {"tranches": ((1.0, mode, k),)}
                if tname == "trail25":
                    kw["trail_stop"] = 0.25
                else:
                    kw["exit_sig"] = sig(p)
                return kw
            defs.append((f"{tname} {mode}*{k}", builder))
    # references
    for d, lab in ((0.0, "tick"), (0.015, "1.5%")):
        def builder(p, sig=sig, d=d, tname=tname):
            kw = {"tranches": ((1.0, "below", d),)}
            if tname == "trail25":
                kw["trail_stop"] = 0.25
            else:
                kw["exit_sig"] = sig(p)
            return kw
        defs.append((f"{tname} REF-{lab}", builder))

wins = ("tune", "valid", "full10")
rows = run2(preps, defs, windows=wins)
rows = print2(rows, windows=wins, sort_by="valid")
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
