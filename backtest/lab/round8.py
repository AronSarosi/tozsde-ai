"""Round 8: window-length robustness. Finalists from rounds 2-7 evaluated on
the 5y split (tune/valid), 6y split (tune6/valid6), 7y split (tune7/valid7)
and full 10y. A finalist survives only if median edge >= 0 on every tune AND
every valid window.
"""
import json
from pathlib import Path
import common as C

OUT = Path(__file__).parent


def trail(t, sf):
    def b(p):
        return {"trail_stop": t, "rebuy_below_sale": True, "sell_frac": sf}
    return b


def zx(L, thr, sf):
    def b(p):
        return {"exit_sig": p[f"z_{L}"] > thr, "rebuy_below_sale": True, "sell_frac": sf}
    return b


def rsi(hi, sf):
    def b(p):
        return {"exit_sig": p["rsi"] > hi, "rebuy_below_sale": True, "sell_frac": sf}
    return b


FINALISTS = [
    ("trail20 below sf1.0", trail(0.20, 1.0)),
    ("trail22 below sf0.5", trail(0.22, 0.5)),
    ("trail25 below sf1.0", trail(0.25, 1.0)),
    ("trail25 below sf0.5", trail(0.25, 0.5)),
    ("trail28 below sf1.0", trail(0.28, 1.0)),
    ("trail28 below sf0.5", trail(0.28, 0.5)),
    ("trail30 below sf1.0", trail(0.30, 1.0)),
    ("z50>2.5 below sf1.0", zx(50, 2.5, 1.0)),
    ("z50>3.0 below sf0.5", zx(50, 3.0, 0.5)),
    ("z100>3.0 below sf1.0", zx(100, 3.0, 1.0)),
    ("z150>3.0 below sf1.0", zx(150, 3.0, 1.0)),
    ("z150>3.0 below sf0.5", zx(150, 3.0, 0.5)),
    ("z200>3.0 below sf0.5", zx(200, 3.0, 0.5)),
    ("rsi75 below sf1.0", rsi(75, 1.0)),
    ("rsi80 below sf1.0", rsi(80, 1.0)),
    ("rsi80 below sf0.5", rsi(80, 0.5)),
]

WINS = ("tune", "valid", "tune6", "valid6", "tune7", "valid7", "full10")


def main():
    mat = C.load()
    preps = C.build_preps(mat)
    rows = C.run_strategies(preps, FINALISTS, windows=WINS)
    (OUT / "round8_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("strategy".ljust(24) + "".join(w.rjust(16) for w in WINS) + "   all>=0?")
    for r in rows:
        cells, ok = [], True
        for w in WINS:
            d = r[w]
            cells.append(f"{d['med_edge']:+7.2f}/{d['pos_pct']:4.0f}%".rjust(16))
            if w != "full10" and d["med_edge"] < 0:
                ok = False
        print(r["name"].ljust(24) + "".join(cells) + ("   SURVIVES" if ok else ""))


if __name__ == "__main__":
    main()
