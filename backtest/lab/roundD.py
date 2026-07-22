"""Round D - two-tranche ladders, sell-half + discount, vol-bucket triggers.

Ladders: sell ALL at trigger; rebuy tranche 1 (weight w) at first tick below
sale, tranche 2 (1-w) deeper (fixed d%, or vol-scaled). Motivation: round A-C
showed discounts lift the median but any all-or-nothing discount can miss a
decade runaway entirely (NVDA -15,000pp). A tick-below tranche guarantees at
least partial re-participation.

Sell-half: sell 50% at trigger, rebuy that half at tick / -d% (deep tranche
only risks half the position).

Vol buckets: stocks bucketed by median vol20 over the TUNE window (no
look-ahead into valid); different sell trigger per bucket.

Windows: tune / valid / full10.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from common2 import (load, build_preps, augment, run2, print2, exit_z,
                     exit_rsi, WINDOWS, window_slice)

mat = load()
preps = build_preps(mat)
augment(preps, mat)
print(f"{len(preps)} symbols")

# --- vol buckets from TUNE window only ---
tw = WINDOWS["tune"]
vols = {}
for s, p in preps.items():
    sl = window_slice(p, tw, 200)
    if sl:
        a, b = sl
        v = np.nanmedian(p["sigma20"][a:b])
        if np.isfinite(v):
            vols[s] = v
q1, q2 = np.quantile(list(vols.values()), [1 / 3, 2 / 3])
BUCKET = {s: (2 if v > q2 else (1 if v > q1 else 0)) for s, v in vols.items()}
print(f"vol terciles: q1={q1:.4f} q2={q2:.4f}; "
      f"hi-vol examples: {[s for s, b in BUCKET.items() if b == 2][:8]}")

TRIG = {
    "z50": lambda p: exit_z(p, 50, 2.5),
    "z150": lambda p: exit_z(p, 150, 3.0),
    "rsi80": lambda p: exit_rsi(p, 80),
}

defs = []
# --- ladders: sell all, rebuy w at tick + (1-w) deeper ---
LADDER_D = [0.02, 0.03, 0.05, 0.08, 0.10]
for tname in ("z50", "z150", "trail25"):
    for w in (0.5, 0.7):
        for d in LADDER_D:
            def builder(p, tname=tname, w=w, d=d):
                kw = {"tranches": ((w, "below", 0.0), (1 - w, "below", d))}
                if tname == "trail25":
                    kw["trail_stop"] = 0.25
                else:
                    kw["exit_sig"] = TRIG[tname](p)
                return kw
            defs.append((f"{tname} L{int(w*100)}tick+{int((1-w)*100)}@-{d*100:.0f}%", builder))
    for mode, k in (("atr", 1.0), ("atr", 2.0), ("sigma", 2.0)):
        def builder(p, tname=tname, mode=mode, k=k):
            kw = {"tranches": ((0.5, "below", 0.0), (0.5, mode, k))}
            if tname == "trail25":
                kw["trail_stop"] = 0.25
            else:
                kw["exit_sig"] = TRIG[tname](p)
            return kw
        defs.append((f"{tname} L50tick+50@{mode}{k}", builder))
    # reference
    def builder(p, tname=tname):
        kw = {"tranches": ((1.0, "below", 0.0),)}
        if tname == "trail25":
            kw["trail_stop"] = 0.25
        else:
            kw["exit_sig"] = TRIG[tname](p)
        return kw
    defs.append((f"{tname} REF-tick", builder))

# --- sell-half variants: sell 50%, rebuy at tick / -d% / atr ---
for tname in ("z50", "z150"):
    for mode, prm, lab in (("below", 0.0, "tick"), ("below", 0.02, "-2%"),
                           ("below", 0.05, "-5%"), ("atr", 1.0, "atr1")):
        def builder(p, tname=tname, mode=mode, prm=prm):
            return {"exit_sig": TRIG[tname](p), "sell_frac": 0.5,
                    "tranches": ((1.0, mode, prm),)}
        defs.append((f"{tname} sellhalf reb@{lab}", builder))

# --- vol-bucket combined triggers (bucketed on TUNE data only) ---
COMBOS = [
    ("hi:rsi80 lo:z50", {2: "rsi80", 1: "z50", 0: "z50"}),
    ("hi:rsi80 mid:z50 lo:z150", {2: "rsi80", 1: "z50", 0: "z150"}),
    ("hi:z50 lo:z150", {2: "z50", 1: "z50", 0: "z150"}),
    ("hi:z50 lo:trail25", {2: "z50", 1: "z50", 0: None}),
]
for cname, mapping in COMBOS:
    def builder(p, mapping=mapping):
        s = p["_symbol"]
        t = mapping.get(BUCKET.get(s, 1), "z50")
        kw = {"tranches": ((1.0, "below", 0.0),)}
        if t is None:
            kw["trail_stop"] = 0.25
        else:
            kw["exit_sig"] = TRIG[t](p)
        return kw
    defs.append((f"bucket {cname} tick", builder))
    def builder2(p, mapping=mapping):
        s = p["_symbol"]
        t = mapping.get(BUCKET.get(s, 1), "z50")
        kw = {"tranches": ((0.5, "below", 0.0), (0.5, "below", 0.03))}
        if t is None:
            kw["trail_stop"] = 0.25
        else:
            kw["exit_sig"] = TRIG[t](p)
        return kw
    defs.append((f"bucket {cname} L50+50@-3%", builder2))

for s, p in preps.items():
    p["_symbol"] = s

wins = ("tune", "valid", "full10")
rows = run2(preps, defs, windows=wins)
rows = print2(rows, windows=wins, sort_by="valid")
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
