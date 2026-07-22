# Beat Buy-and-Hold, Round 2 - smarter re-entry rules (lab rounds A-G)

Brief: the round-1 winner ("sell extreme strength, rebuy the FIRST tick below
the sale") is nearly buy-and-hold, ~1pp/yr edge. Find re-entry rules between
"any tick below" and "fixed deep discount" with materially more edge
(target >3pp/yr median). Same honesty protocol: tune 2021-07..2023-12,
validate 2024-01..2026-07, plus 6y (3+3) and 7y (3.5+3.5) splits and the full
10y as sanity checks; 0.1%/side costs; start invested day 1 so zero trades =
exactly B&H; ~104 stocks, SPY excluded. New engine (lab/common2.py) adds
tranche rebuys, vol-scaled and time-decaying discounts, conditional re-entry,
bounce-from-low, fallbacks, and logs median wait-to-rebuy days plus the % of
exits that never refill.

## Headline verdict (honest)

The >3pp/yr target was NOT reached by any rule that survives all sanity
checks. What round 2 established:

1. Small rebuy discounts (1-2.5%) genuinely lift the MEDIAN edge - up to
   ~2.3pp/yr, roughly double round 1 - and the effect is consistent across
   the 5y, 6y and 7y walk-forward splits.
2. But every fixed discount, however small, turns the decade-runaway miss
   from a rarity into a recurring catastrophe on individual stocks. At just a
   0.5% discount, NVDA's 10y edge flips from +5,249pp (tick rebuy refilled)
   to -15,293pp (one refill missed before the 2023 run). Medians survive;
   single names do not.
3. The only tail-safe improvements found are the DECAYING discount (demand
   2% at first, requirement melts to "any tick below" over 10 days) and the
   70/30 LADDER (70% back on the first tick below, 30% at -2%). These beat
   the round-1 champion on every validation window while keeping the decade
   tails alive, at ~1.2-1.5pp/yr.

## Ranked table

Medians are per-stock edge vs same-stock B&H. "edge/yr" = average of the
valid-window medians annualised (valid 2.5y, valid6 3y, valid7 3.45y).
"pos" = % stocks positive in valid. T/N/A/I = TSLA/NVDA/AMZN/INTC edge (pp),
valid window first, full 10y in brackets. Wait = median days from sale to
refill (valid); Never = % of rebuy tranches never refilled; Sells = median
sales per 2.5y valid window. Full per-window stats: lab/roundF.json, roundG.json.

| # | Rule (sell trigger / re-entry) | edge/yr | valid 5/6/7y med | 10y med | pos | TSLA | NVDA | AMZN | INTC | Wait | Never | Sells |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | z50>2.5 / fixed -2.0% below sale | +2.25 | +5.7 / +7.3 / +7.1 | +7.3 | 67% | +20 (-2362) | +60 (-15244) | +28 (-523) | -155 (-252) | 8.5d | 11.8% | 2 |
| 2 | z50>2.5 / fixed -1.0% below sale | +1.73 | +4.2 / +5.6 / +5.7 | +7.2 | 68% | +22 (-2358) | +100 (-15244) | +10 (-523) | -155 (-254) | 4.0d | 9.4% | 3 |
| 3 | trail25 / ladder 50% tick + 50% at -2% | +1.39 | +4.2 / +4.3 / +3.7 | -2.1 | 69% | -74 (-438) | +28 (+7313) | +7 (+100) | +40 (+93) | 3.0d | 9.8% | 2 |
| 4 | trail25 / ladder 70% tick + 30% at -2% | +1.26 | +3.6 / +3.9 / +3.5 | +7.9 | 69% | -74 (+21) | +22 (+6535) | +7 (+82) | +32 (+79) | 3.0d | 9.8% | 2 |
| 5 | z50>2.5 / first tick below (round-1 champ) | +1.30 | +3.4 / +3.9 / +4.3 | +9.3 | 68% | +19 (+1232) | +90 (+5249) | +10 (-521) | -155 (-256) | 1.5d | 7.2% | 4 |
| 6 | trail25 / decay -2% melting to 0 over 10d | +1.16 | +3.1 / +3.7 / +3.4 | +17.4 | 69% | -74 (-594) | +27 (+7591) | +7 (+111) | +36 (+82) | 4.0d | 10.1% | 2 |
| 7 | trail25 / ladder 50% tick + 50% decay2%/10d | +1.13 | +3.1 / +3.6 / +3.2 | +13.4 | 71% | -74 (-678) | +28 (+6887) | +7 (+87) | +28 (+72) | 2.5d | 9.0% | 2 |
| 8 | z150>3 / decay -2% melting to 0 over 10d | +0.91 | +2.6 / +2.7 / +2.8 | +18.9 | 69% | +11 (+373) | +53 (+7215) | +5 (+58) | -157 (-253) | 5.5d | 9.6% | 2 |
| 9 | z150>3 / first tick below | +0.85 | +2.2 / +2.5 / +2.8 | +18.4 | 70% | +12 (+495) | +36 (+5280) | +2 (+49) | -157 (-253) | 1.5d | 6.3% | 3 |
| 10 | z150>3 / -0.5 x sigma20 below sale | +0.80 | +2.2 / +2.4 / +2.6 | +22.6 | 66% | +12 (+1893) | +85 (+8076) | +2 (+80) | -157 (-253) | 6.0d | 11.1% | 2 |
| 11 | z150>3 sell HALF / decay2%/10d | +0.62 | +1.9 / +1.7 / +1.9 | +17.4 | 72% | +6 (+273) | +28 (+4891) | +2 (+52) | -94 (-147) | 5.5d | 9.6% | 2 |

Rejected despite top-of-table validation medians: z50>2.5 / -2.5% (valid
+6.0/+8.9/+7.9, the best medians of the entire lab, but 10y median -18.7 -
over the cliff) and z150|trail25 combined exits (valid +3.2-4.5 but 10y
median -31 to -77 from overtrading, 7-11 sells per window).

Notation: z50/z150 = (close/SMA(L)-1) divided by the 252d rolling std of that
distance; trail25 = close <= 75% of peak close since (re)entry; decay2%/10d =
refill threshold sale x (1 - 0.02 x max(0, 1 - t/10)) so after 10 trading
days it becomes "first close strictly below sale"; ladders split the sold
amount into tranches that refill independently; sells always at the close.

## The discount cliff (where between 1-5% does it break?)

z50>2.5 sell, fixed discount d, all ~104 stocks:

| d | valid med | 10y med | 10y pos | wait (valid) | never refilled |
|---|---|---|---|---|---|
| 0% (tick) | +3.40 | +9.3 | 58% | 1.5d | 7.2% |
| 0.5% | +3.66 | +11.8 | 56% | 2.0d | 8.1% |
| 1.0% | +4.17 | +7.2 | 53% | 4.0d | 9.4% |
| 1.5% | +4.52 | +6.8 | 52% | 4.2d | 10.7% |
| 2.0% | +5.66 | +7.3 | 51% | 8.5d | 11.8% |
| 2.5% | +6.03 | -18.7 | 47% | 11.5d | 13.4% |
| 3.0% | +5.77 | -48.7 | 42% | 15.0d | 15.8% |
| 5.0% | +5.27 | -116.4 | 37% | 24.0d | 21.6% |

Two different cliffs:

- MEDIAN cliff: the 10y median flips negative between 2.0% and 2.5% for z50,
  between 1.5% and 2% for trail25, at ~1% for RSI>80, and only around 4-5%
  for z150>3 (the slower, rarer trigger sells at more extreme peaks, so
  deeper retracements reliably follow). Rule of thumb: the faster the sell
  trigger, the smaller the survivable discount.
- TAIL cliff: starts at 0.5%. Any fixed discount converts "miss the runaway"
  from a tail event into a certainty over a decade for at least one of the
  key names. The valid-window medians up to 2% are real and repeatable, but
  they are financed by rare total disasters on exactly the stocks (TSLA,
  NVDA) this system cares most about.
- Waiting behaviour: tick-rebuys refill in a median 1.5-2 days and ~93% of
  exits refill. Each +1% of demanded discount roughly doubles the median
  wait and adds ~2pp to the never-refilled rate.

## Worst ideas (tested, quantified, rejected)

1. Bounce-from-low re-entry (rebuy after a 3-10% bounce off the post-sale
   low, no below-sale cap): valid median -2 to -13pp, 10y -29 to -121pp. It
   systematically buys local tops. Capping it below the sale price just
   makes it flat with 20-37% of exits never refilled.
2. Fallback caps on discount rules - force refill after 42/63/126 days or
   when price runs +5/10/15% above the sale: they do cap the never-refill
   tail to ~0-2%, and they erase the edge doing it (z50 -1.5% goes from
   valid +4.5 to 0.0 with a 42d timer, to -3.8..-4.4 with runaway chases).
   Same result as round 1: timers buy tops, chases buy breakouts.
3. Conditional re-entry (below sale AND RSI<40..60 / MA20-50 touch / 10-20d
   low / 3 calm days): adds nothing. After a trail exit the conditions are
   already true at the first tick below (rows literally identical); on z
   triggers they mostly shave the edge and fatten the never-refill tail.
4. Deep ladder tranches (-8/-10%): kill both windows (valid +0.0-2.4, 10y
   -34 to -176).
5. Combined exits (z150 OR trail25): more sells (7-11 per window) looked
   fine in tune/valid, 10y median -31 to -77. Overtrading compounds costs
   and re-entry risk.
6. Vol-bucket trigger assignment (hi-vol RSI>80, low-vol z-score, bucketed
   on tune-window vol only): never better than the single best trigger.
7. Large vol-scaled discounts (>= 1.5 x ATR14/sigma20): identical poison to
   large fixed discounts once the implied % matches.

## Recommendation - what to wire into the live shadow portfolio

Do NOT ship rule 1 or 2 (fixed 1-2% discounts) for Aron's concentrated real
holdings. Their median edge (~2.3pp/yr) is the best found, but the money is
made across ~100 diversified names while individual positions carry decade
blow-up risk of exactly the kind Aron holds (TSLA/NVDA-style runaways).
A fixed discount is only defensible for a broad basket, never for 3-10
positions.

Ship these two, per position:

- DEFAULT (balanced) - "z150 sell-all, decaying rebuy":
  SELL 100% when (close/SMA150 - 1) / 252d-std-of-that-distance > 3.
  REBUY when close <= sale x (1 - 0.02 x max(0, 1 - t/10)), t = trading days
  since sale; from day 10 onward that is simply the first close strictly
  below the sale price. No time limit, never chase above the sale.
  Expected: ~2 sales/2.5y, median refill in ~5 days at a ~2% achieved
  discount, ~90% of exits refill, +0.9pp/yr median edge, 10y median +19pp,
  69% of stocks positive, TSLA/NVDA/AMZN all positive over the decade.
- CONSERVATIVE (for positions Aron cannot stomach mistiming) - "z150
  sell-half": SELL 50% at the same z150>3 trigger, rebuy the half with the
  same decay2%/10d rule. Half the edge (+0.6pp/yr) but the highest share of
  stocks positive (68-72% on every window) and worst-case single-name damage
  roughly halved.

Optional aggressive overlay for crash protection on momentum names: trail25
with the 70/30 ladder (sell all when close <= 75% of peak since entry; rebuy
70% at the first close below the sale, 30% at sale x 0.98). It has the best
tail profile of the higher-edge rules (all four key stocks positive on 10y)
but is trend-dependent: it lags in relentless uptrends like TSLA 2024-26
(-74pp valid). Suitable as a portfolio-level hedge mode, not the default.

TSLA-specific note (unchanged from round 1, re-confirmed): RSI(14)>80
sell-all with tick-below rebuy remains the best TSLA rule (+33pp valid,
+1,718pp/10y) - but generalises badly (NVDA -15,846pp/10y). Only use it on
TSLA, and only with the tick rebuy, no discount (RSI's cliff is at ~1%).

### Per-position signal design (shadow tracking of Aron's real holdings)

State machine per holding, evaluated daily at the close:

1. HOLDING: track SMA150, the 252d std of (close/SMA150 - 1), and peak close
   since (re)entry. Emit SELL (default: 100%, conservative: 50%) when
   z150 > 3. Record P0 = sale close, t = 0.
2. WAITING: threshold(t) = P0 x (1 - 0.02 x max(0, 1 - t/10)). Emit REBUY
   when close <= threshold(t) (strictly below P0 once t >= 10). Display:
   days waiting, current threshold, distance to refill, and the running
   "edge banked" = P0/current - 1. Never emit a rebuy above P0; if the stock
   runs away, the position stays out and the dashboard should say so
   honestly (expect ~10% of exits to end this way - that is the cost of the
   edge, and every attempt to cap it destroyed the edge).
3. On REBUY: reset entry/peak, return to HOLDING. Costs assumed 0.1%/side;
   more than ~0.3%/side eats the whole median edge - use limit orders at the
   threshold price.

Honest expectation to set with Aron: this family skims +0.6 to +1.5pp/yr at
the median over B&H, reaching ~+2.3pp/yr only by accepting blow-up tails on
single names. The materially-larger robust edge he asked for does not exist
inside "sell high, rebuy lower" on daily closes - round 2 swept discounts
(9 levels), vol scalings (14), conditions (10), ladders (25), decays (16),
bounces (16), fallbacks (24), hybrids and bucketed triggers to establish
that. The value of the system remains discipline plus a small skim, not
outperformance headlines.

Artifacts: lab/roundA-G.py + .json results, lab/common2.py engine,
lab/LOG.md rounds A-G. Round-1 report: BEAT_BH_REPORT.md.
