"""Round C - conditional re-entry + fallback caps.

Part 1: rebuy on first close BELOW SALE that also satisfies a condition
(RSI(14)<x, touch of 20/50d MA, 10/20-day low, 3 calm days). The discount
"emerges naturally" instead of being demanded.

Part 2: fallback caps on the discount rules that had the best valid medians
but poisoned decade tails (z50>2.5 + 1/1.5/2% discount, z150>3 + 0.5*ATR):
force refill after N days out (42/63/126) or when price runs +x% above sale
(5/10/15%). Quantifies what each fallback costs/buys.

Windows: tune / valid / full10.
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
CONDS = ["rsi_lt_40", "rsi_lt_45", "rsi_lt_50", "rsi_lt_55", "rsi_lt_60",
         "touch_ma20", "touch_ma50", "is_lo10", "is_lo20", "calm3"]

defs = []
for tname, sig in TRIGGERS:
    for cond in CONDS:
        def builder(p, sig=sig, cond=cond, tname=tname):
            kw = {"tranches": ((1.0, "cond", cond),)}
            if tname == "trail25":
                kw["trail_stop"] = 0.25
            else:
                kw["exit_sig"] = sig(p)
            return kw
        defs.append((f"{tname} below&{cond}", builder))
    def builder(p, sig=sig, tname=tname):
        kw = {"tranches": ((1.0, "below", 0.0),)}
        if tname == "trail25":
            kw["trail_stop"] = 0.25
        else:
            kw["exit_sig"] = sig(p)
        return kw
    defs.append((f"{tname} REF-tick", builder))

# Part 2: fallbacks on the tail-poisoned discount stars
FALL = ([("mo", m) for m in (42, 63, 126)] + [("gu", g) for g in (0.05, 0.10, 0.15)]
        + [(None, None)])
BASES = [("z50>2.5", lambda p: exit_z(p, 50, 2.5), ("below", 0.01), "d1.0%"),
         ("z50>2.5", lambda p: exit_z(p, 50, 2.5), ("below", 0.015), "d1.5%"),
         ("z50>2.5", lambda p: exit_z(p, 50, 2.5), ("below", 0.02), "d2.0%"),
         ("z150>3", lambda p: exit_z(p, 150, 3.0), ("atr", 0.5), "atr0.5"),
         ("z150>3", lambda p: exit_z(p, 150, 3.0), ("atr", 0.75), "atr0.75")]
for tname, sig, (mode, prm), lab in BASES:
    for fkind, fval in FALL:
        if fkind is None and lab in ("d1.5%",):  # ref already in part 1 style
            continue
        def builder(p, sig=sig, mode=mode, prm=prm, fkind=fkind, fval=fval):
            kw = {"exit_sig": sig(p), "tranches": ((1.0, mode, prm),)}
            if fkind == "mo":
                kw["max_out"] = fval
            elif fkind == "gu":
                kw["giveup_up"] = fval
            return kw
        fl = "" if fkind is None else (f" out>{fval}d" if fkind == "mo"
                                       else f" run+{fval*100:.0f}%")
        defs.append((f"{tname} {lab}{fl}", builder))

wins = ("tune", "valid", "full10")
rows = run2(preps, defs, windows=wins)
rows = print2(rows, windows=wins, sort_by="valid")
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
