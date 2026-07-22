"""Round E - decaying discounts and bounce-from-low re-entries.

Decay: demand sale*(1-d0) initially, requirement decays linearly to "any tick
below sale" over T days. Captures quick dips at a discount; worst case
converges to the proven tick-below rule instead of never refilling.
Grid: d0 in {2,3,5,8}%, T in {10,21,42,63} days.

Bounce: rebuy when price has bounced b% off its low since the sale
(b in {3,5,8,10}%), capped (must still be below sale) and uncapped.
Also ladder combos: 50% tick + 50% decay/bounce.

Triggers: z50>2.5, z150>3, trail25. Windows: tune / valid / full10.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common2 import load, build_preps, augment, run2, print2, exit_z

mat = load()
preps = build_preps(mat)
augment(preps, mat)
print(f"{len(preps)} symbols")

TRIG = {"z50": lambda p: exit_z(p, 50, 2.5),
        "z150": lambda p: exit_z(p, 150, 3.0),
        "trail25": None}


def mk(tname, tranches):
    def builder(p, tname=tname, tranches=tranches):
        kw = {"tranches": tranches}
        if tname == "trail25":
            kw["trail_stop"] = 0.25
        else:
            kw["exit_sig"] = TRIG[tname](p)
        return kw
    return builder


defs = []
for tname in ("z50", "z150", "trail25"):
    for d0 in (0.02, 0.03, 0.05, 0.08):
        for T in (10, 21, 42, 63):
            defs.append((f"{tname} decay{d0*100:.0f}%/{T}d",
                         mk(tname, ((1.0, "decay", (d0, T)),))))
    for b in (0.03, 0.05, 0.08, 0.10):
        defs.append((f"{tname} bounce{b*100:.0f}%<sale",
                     mk(tname, ((1.0, "bounce", (b, True)),))))
        defs.append((f"{tname} bounce{b*100:.0f}%any",
                     mk(tname, ((1.0, "bounce", (b, False)),))))
    defs.append((f"{tname} L50tick+50decay5%/42d",
                 mk(tname, ((0.5, "below", 0.0), (0.5, "decay", (0.05, 42))))))
    defs.append((f"{tname} L50tick+50bounce5%<sale",
                 mk(tname, ((0.5, "below", 0.0), (0.5, "bounce", (0.05, True))))))
    defs.append((f"{tname} REF-tick", mk(tname, ((1.0, "below", 0.0),))))

wins = ("tune", "valid", "full10")
rows = run2(preps, defs, windows=wins)
rows = print2(rows, windows=wins, sort_by="valid")
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
