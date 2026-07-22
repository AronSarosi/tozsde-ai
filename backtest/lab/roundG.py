"""Round G - hybrid re-entries: ladder + decay, combined exits.

The ladder (70% tick + 30% @-2%) and the decay (discount melts to zero over
10-21d) each beat the pure tick-below on validation while keeping the decade
tail alive. Test their combination, plus the z150-OR-trail25 combined exit.
All 7 honesty windows.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common2 import load, build_preps, augment, run2, exit_z

mat = load()
preps = build_preps(mat)
augment(preps, mat)
print(f"{len(preps)} symbols")

Z150 = lambda p: exit_z(p, 150, 3.0)

DEFS = [
    ("trail25 L70tick+30decay2%/10d",
     lambda p: {"trail_stop": 0.25,
                "tranches": ((0.7, "below", 0.0), (0.3, "decay", (0.02, 10)))}),
    ("trail25 L70tick+30decay3%/21d",
     lambda p: {"trail_stop": 0.25,
                "tranches": ((0.7, "below", 0.0), (0.3, "decay", (0.03, 21)))}),
    ("trail25 L50tick+50decay2%/10d",
     lambda p: {"trail_stop": 0.25,
                "tranches": ((0.5, "below", 0.0), (0.5, "decay", (0.02, 10)))}),
    ("z150 L70tick+30decay2%/10d",
     lambda p: {"exit_sig": Z150(p),
                "tranches": ((0.7, "below", 0.0), (0.3, "decay", (0.02, 10)))}),
    ("z150 L50tick+50decay3%/21d",
     lambda p: {"exit_sig": Z150(p),
                "tranches": ((0.5, "below", 0.0), (0.5, "decay", (0.03, 21)))}),
    ("z150 sellhalf decay2%/10d",
     lambda p: {"exit_sig": Z150(p), "sell_frac": 0.5,
                "tranches": ((1.0, "decay", (0.02, 10)),)}),
    ("z150|trail25 tick",
     lambda p: {"exit_sig": Z150(p), "trail_stop": 0.25,
                "tranches": ((1.0, "below", 0.0),)}),
    ("z150|trail25 decay2%/10d",
     lambda p: {"exit_sig": Z150(p), "trail_stop": 0.25,
                "tranches": ((1.0, "decay", (0.02, 10)),)}),
    ("z150|trail25 L70tick+30@-2%",
     lambda p: {"exit_sig": Z150(p), "trail_stop": 0.25,
                "tranches": ((0.7, "below", 0.0), (0.3, "below", 0.02))}),
]

wins = ("tune", "valid", "tune6", "valid6", "tune7", "valid7", "full10")
rows = run2(preps, DEFS, windows=wins)
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
for r in rows:
    print(f"\n== {r['name']}")
    for w in wins:
        d = r[w]
        print(f"  {w:7s} medE {d['med_edge']:+8.2f}  pos {d['pos_pct']:5.1f}%  "
              f"sells {d['med_sells']:4.1f}  tim {d['med_tim']:5.1f}%  "
              f"wait {d['med_wait']}  disc {d['med_disc']}  never {d['never_pct']:4.1f}%  "
              f"T/N/A/I {d['TSLA']}/{d['NVDA']}/{d['AMZN']}/{d['INTC']}")
