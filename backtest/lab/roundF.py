"""Round F - finalists across all 7 honesty windows.

Best candidates from rounds A-E on: 5y tune/valid, 6y tune6/valid6,
7y tune7/valid7, full10. Full stats for the ROUND2 report, incl. median
wait-to-rebuy and % of tranches never refilled.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from common2 import load, build_preps, augment, run2, exit_z, exit_rsi

mat = load()
preps = build_preps(mat)
augment(preps, mat)
print(f"{len(preps)} symbols")

Z50 = lambda p: exit_z(p, 50, 2.5)
Z150 = lambda p: exit_z(p, 150, 3.0)
COMBO = lambda p: exit_z(p, 150, 3.0) | exit_rsi(p, 80)

FIN = [
    ("z50 tick (prior champ)",      lambda p: {"exit_sig": Z50(p), "tranches": ((1.0, "below", 0.0),)}),
    ("z50 d1.0%",                   lambda p: {"exit_sig": Z50(p), "tranches": ((1.0, "below", 0.01),)}),
    ("z50 d2.0%",                   lambda p: {"exit_sig": Z50(p), "tranches": ((1.0, "below", 0.02),)}),
    ("z50 d2.5%",                   lambda p: {"exit_sig": Z50(p), "tranches": ((1.0, "below", 0.025),)}),
    ("z50 sellhalf d2.0%",          lambda p: {"exit_sig": Z50(p), "sell_frac": 0.5, "tranches": ((1.0, "below", 0.02),)}),
    ("z150 tick",                   lambda p: {"exit_sig": Z150(p), "tranches": ((1.0, "below", 0.0),)}),
    ("z150 atr*0.5",                lambda p: {"exit_sig": Z150(p), "tranches": ((1.0, "atr", 0.5),)}),
    ("z150 sigma*0.5",              lambda p: {"exit_sig": Z150(p), "tranches": ((1.0, "sigma", 0.5),)}),
    ("z150 decay2%/10d",            lambda p: {"exit_sig": Z150(p), "tranches": ((1.0, "decay", (0.02, 10)),)}),
    ("z150 decay3%/10d",            lambda p: {"exit_sig": Z150(p), "tranches": ((1.0, "decay", (0.03, 10)),)}),
    ("z150 L50tick+50@-2%",         lambda p: {"exit_sig": Z150(p), "tranches": ((0.5, "below", 0.0), (0.5, "below", 0.02))}),
    ("z150 sellhalf tick",          lambda p: {"exit_sig": Z150(p), "sell_frac": 0.5, "tranches": ((1.0, "below", 0.0),)}),
    ("z150 sellhalf decay3%/10d",   lambda p: {"exit_sig": Z150(p), "sell_frac": 0.5, "tranches": ((1.0, "decay", (0.03, 10)),)}),
    ("z150|rsi80 decay3%/10d",      lambda p: {"exit_sig": COMBO(p), "tranches": ((1.0, "decay", (0.03, 10)),)}),
    ("trail25 tick",                lambda p: {"trail_stop": 0.25, "tranches": ((1.0, "below", 0.0),)}),
    ("trail25 decay2%/10d",         lambda p: {"trail_stop": 0.25, "tranches": ((1.0, "decay", (0.02, 10)),)}),
    ("trail25 decay2%/21d",         lambda p: {"trail_stop": 0.25, "tranches": ((1.0, "decay", (0.02, 21)),)}),
    ("trail25 L70tick+30@-2%",      lambda p: {"trail_stop": 0.25, "tranches": ((0.7, "below", 0.0), (0.3, "below", 0.02))}),
    ("trail25 L50tick+50@-2%",      lambda p: {"trail_stop": 0.25, "tranches": ((0.5, "below", 0.0), (0.5, "below", 0.02))}),
]

wins = ("tune", "valid", "tune6", "valid6", "tune7", "valid7", "full10")
rows = run2(preps, FIN, windows=wins)
Path(__file__).with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))

for r in rows:
    print(f"\n== {r['name']}")
    for w in wins:
        d = r[w]
        print(f"  {w:7s} medE {d['med_edge']:+8.2f}  pos {d['pos_pct']:5.1f}%  "
              f"sells {d['med_sells']:4.1f}  tim {d['med_tim']:5.1f}%  "
              f"wait {d['med_wait']}  disc {d['med_disc']}  never {d['never_pct']:4.1f}%  "
              f"T/N/A/I {d['TSLA']}/{d['NVDA']}/{d['AMZN']}/{d['INTC']}")
