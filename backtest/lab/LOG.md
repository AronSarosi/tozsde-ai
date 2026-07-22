# Beat-Buy-and-Hold Lab - running log

Setup (common.py): 105 symbols, 10y daily closes. Windows: TUNE 2021-07..2023-12,
VALID 2024-01..2026-07, FULL5, FULL10. Cost 0.1% per side (B&H pays the entry cost
too, so zero trades = exactly B&H). Every strategy starts INVESTED day 1, so edge
can only come from round trips - this kills the old degenerate "never enter" case.
Metric: per-stock edge = strat total return - B&H total return (pp), aggregated as
median edge + % of stocks with positive edge (SPY excluded from aggregates).

## Round 1 - overextension take-profit + pullback rebuy (round1.py)

Grid: sell when z200 > {1.5,2,2.5,3} or pct_dist(3y) > {0.95,0.98}; rebuy on
{5/10/15% drop below sale, price<=MA200, z<0.5}; give-up maxout {None, 60d}.

Results:
- Almost everything is NEGATIVE in VALID (2024-26 bull). Selling "high" and
  waiting for a big pullback means being flat while NVDA doubles: worst cells
  show NVDA edge -260..-307pp. Aggressive thresholds (z>1.5..2) lose 15-34pp median.
- The ONLY non-negative cell: sell z>3.0, rebuy after 5% drop, never give up:
  TUNE +0.00 (58% pos), VALID +2.86 (61% pos), ~1 sell, 80-98% time in market.
- Pattern: the tighter the rebuy (5% vs 15%) and the rarer the sell (z>3), the
  better. Give-up timers (maxout 60) HURT - they force rebuys at highs.

Hypothesis for round 2: the profitable shape is "skim small slices off extreme
spikes, rebuy fast and lower". Test trailing-stop take-profits + rebuy-lower-only,
and even tighter rebuy thresholds (any price below sale).

## Round 2 - trailing-high take-profit, rebuy lower only (round2.py)

Grid: trailing stop T {10,15,20,25}% from peak-since-entry, armed always or only
after peak >= entry+{25,50}% ; plain profit targets {30,50,100}% ; rebuy strictly
below sale price or 5% below; give-up maxout {None,10,30,90}.

Results - first genuinely two-sided winners:
- trail20 (no gain arm) + rebuy-below-sale + never give up:
  TUNE +2.84 (78% pos), VALID +3.39 (64% pos), ~4 sells, 92-95% time in.
- trail25 same: TUNE +2.49 (79%), VALID +2.55 (68%).
- trail15 same: TUNE +4.08 (66%), VALID +2.36 (57%).
- trail25 armed after +25% gain + rebuy-below: VALID 78.8% pos (+2.77), TUNE 68% pos.
- VALID top cell (trail25 gain25 + rebuy drop5) is +7.11 but +0.00/0-sells in TUNE
  (rarely triggers there) - weak evidence, treat carefully.
- Short give-up timers (maxout 10-30) consistently degrade both windows.
- The failure mode remains the runaway stock: rebuy-below-sale never fills when a
  stock V-recovers and rockets (NVDA cells -75..-290pp), but the median stock chops
  enough that rebuy fills lower -> positive median edge.

Interpretation: a WIDE trailing exit (20-25%) acts as crash protection during
2022-style declines, and the rebuy-below-sale constraint locks in the buyback
discount. This is exactly Aron's TSLA move formalized. The trade-off is missing
V-shaped rockets.

Hypothesis for round 3: an oscillator (RSI) may time re-entry better than a pure
price constraint; also test RSI-based take-profits.

## Round 3 - RSI overlays (round3.py)

Grid: sell RSI(14) > {70,75,80,85}; rebuy RSI < {40,50,60} (with/without the
rebuy-lower-only constraint stacked), pure rebuy-below-sale, drop5%; maxout {None,30,90}.

Results:
- Best two-sided: RSI>75 + rebuy-below-sale, never give up: TUNE +1.84 (66% pos),
  VALID +2.51 (61% pos), 4-5 sells. RSI>80 + below: TUNE 0.00 (58%), VALID +1.28 (69%).
- Pure RSI re-entries (RSI<40/50/60 without the below-sale constraint) are flat to
  negative in both windows. RSI>85 almost never fires (medians 0.00).
- NVDA is again the killer: -300pp on many cells (RSI>80 sales during a structural
  uptrend never get a lower rebuy).

Learning: the oscillator adds nothing beyond the rebuy-below-sale constraint;
family ranking so far: trailing-stop+below > RSI+below > overextension z-score.

## Round 4 - trend filter (200d MA) + vol-regime (round4.py)

Grid: exit below MA{50,200} (buffer 0/2/5%), re-enter on reclaim, +/- below-sale
constraint; vol-regime exit at vol20 > {1.5,2,2.5}x own 252d median, re-enter <1.25x.

Results - WORST families so far:
- Classic per-stock trend following is a disaster at daily granularity with costs:
  MA200 exit/reclaim = -27 to -31pp median in VALID (22-29% pos). MA50 versions
  -35 to -60pp. Whipsaw on single stocks is far worse than on indices.
- Adding below-sale to a trend exit makes it WORSE (time-in collapses to ~20%:
  you exit downtrends low and the "below sale" fill just puts you back into
  falling knives, or never fills after recovery).
- Vol-regime: mostly ~0 (rarely fires) or negative; the one positive tune cell
  (vol>1.5x + below: +9.08 tune) collapses to -29.4 in valid -> overfit, rejected.

Learning: for SINGLE STOCKS, "get out when weak / get back in when strong" loses
to B&H after costs; only "get out when EXTREMELY strong or after a deep peak-drop,
get back in strictly lower" has shown a two-sided edge.

## Round 5 - partial profit-taking + combos + robustness (round5.py)

Grid: trail {12..30} x {full, half} exits x rebuy-below-sale; rebuy-discount
variants (2/5/8% below sale); combo exits (trail OR z>3 / OR RSI>80); 10y check.

Results - the 10y column is the reality check:
- Tight/medium trails (12-22, full exit) look fine on 5y but are CATASTROPHIC on
  10y: missing one 10x runaway (TSLA 2020, NVDA 2023) costs thousands of pp
  (trail18 below: full10 median -173pp, TSLA -2400pp cells). Requiring an extra
  2-8% rebuy discount makes it much worse (-100..-350pp median full10).
- ROBUST-ON-ALL-3-WINDOWS region = WIDE trail + below-sale + never give up:
    trail25 below full exit : +2.49 / +2.55 / +15.25 (79/68/61% pos)
    trail25 below half exit : +1.46 / +1.82 / +10.42 (80/69/64% pos)
    trail22 below half exit : +1.78 / +2.63 / +9.84
    trail30 below full exit : +1.47 / +1.46 / +7.11
    z>3 below half exit     :  0.00 / +1.61 / +10.75 (66/71/62% pos)
- Combos (trail OR z / OR RSI) add nothing over the pure wide trail.

Learning: partial (half) exits and wider trails both work by capping the damage
of the one failure mode - the runaway stock you never rebuy. Next: cap it
directly with an upside give-up (force rebuy if price breaks +X% above sale).

## Round 6 - upside give-up + fine sweep of the robust region (round6.py)

Added engine param giveup_up: while waiting to rebuy lower, force re-entry if
price breaks +X% ABOVE the sale price (cap the runaway miss at ~X pp).

Results: give-up-up CAPS the tails (full10 TSLA cells improve from -2300pp to
-600..-1100pp) but consistently SHAVES the median edge in tune and valid
(e.g. trail25: +2.55 -> +2.03 with gup50, +0.18 with gup20). The median stock
chops, so chasing +20/30% breakouts mostly buys local tops. Rejected for the
headline rules; noted as a variance-reduction option.

Robust core confirmed: trail 25-28% + below-sale + never give up; half-exits
(sf0.5) trade a little median for much better 10y behaviour.

## Round 7 - lookback sweeps everywhere (Aron directive) (round7.py)

Swept MA lookback L in {50,100,150,200,250,300,400,500} for: overextension
z_L > {2.5,3}, percentile pct_L > 0.98, trend filter exit/reclaim (150-500,
buffer 0/5%), vol-regime with median lookback {126,252,504} x {2,2.5}x.

Results:
- Overextension IMPROVES with shorter lookbacks: z50/z100/z150 + rebuy-below-sale
  beat the original z200. Best all-3-window cells:
    z50>2.5 below sf1.0 : +1.42 / +3.40 / +9.29  (76/68/58% pos)
    z150>3.0 below sf1.0:  0.00 / +2.21 / +18.40 (64/70/64% pos)
    z100>3.0 below sf1.0:  0.00 / +1.82 / +13.80
  The drop5-rebuy variants of the same signals still die on full10 (-30..-160pp):
  the extra discount requirement is the poison, not the signal.
- Trend following is dead at EVERY lookback: ma150..ma500 exit/reclaim all
  -20..-36pp valid, -170..-260pp full10, pos% 14-32. Family conclusively rejected
  with sweep evidence.
- Vol-regime dead at every median lookback: 0 to -9pp valid, -50..-77pp full10.

## Round 8 - window-length robustness 5y/6y/7y (round8.py)

16 finalists evaluated on tune/valid (5y, 2.5+2.5), tune6/valid6 (6y, 3+3),
tune7/valid7 (7y, 3.5+3.5) and full10. ALL 16 have median edge >= 0 on every
tune AND valid window - the "sell high, rebuy strictly lower" family is not
window-specific. 10y separates them: trail20 (-39.65) and rsi75 (-188.6!) fail
the decade; trail25/trail22-sf0.5/z50/z100/z150/z200/rsi80 are positive on all
seven windows.

## Round 9 - TSLA deep dive + trade traces (round9.py)

- Best TSLA-specific rule: RSI(14)>80 sell all, rebuy first close strictly below
  sale: tune +11.6, valid +33.0, full5 +57.7, full10 +1717.8pp, ~4 sells/window.
  Runner-up: z100>2.5 (+7.9/+22.1/+38.1/+1806.5) and z50>2.5 (+9.5/+19.1/+37.3/+1232.2).
- Trace sanity checks: z50>2.5 sold TSLA 2021-10-29 @371 (the melt-up top),
  rebought 341; sold the Nov-Dec 2024 melt-up 3x, each rebuy lower. trail25 on
  NVDA full5: +1137% vs B&H +928% via four lower-rebuys through 2022.
- Failure mode visible too: trail25 on TSLA full5 +12% vs +67% B&H (trailing
  exits into V-recoveries; last sale 2024-08 @192 never refilled below).

Conclusion -> BEAT_BH_REPORT.md

---

# ROUND 2 - smarter re-entry rules (roundA-G, common2.py engine)

Goal (Aron): the tick-below rebuy is nearly B&H (~1pp/yr edge). Find re-entry
rules between "any tick below" and "fixed deep discount" with materially more
edge (target >3pp/yr median). New engine common2.py: tranche rebuys, vol-scaled
discounts (close-based ATR14% / sigma20 frozen at sale), conditional re-entry,
decaying discounts, bounce-from-low, fallbacks; logs median wait-to-rebuy days,
achieved rebuy discount, and % of tranches never refilled.

## Round A - the discount cliff (roundA.py)

Grid: 4 proven sells (z50>2.5, z150>3, trail25, rsi80) x fixed rebuy discount
d in {0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5}%; tune/valid/full10.

- Small discounts DO lift the median: z50+2.5% = valid +6.03 (vs +3.40 at tick),
  z50+2.0% +5.66, trail25+2% +4.17. Median wait grows 1.5d (tick) -> 8-12d (2-2.5%);
  never-refilled grows 7% -> 13% of exits.
- The MEDIAN cliff: z50 flips 10y-negative between 2.0% (+7.3) and 2.5% (-18.7);
  trail25 between 1.5% (+7.9) and 2% (-14.6); rsi80 already dead at 1% (-9);
  z150 tolerates up to ~4% (+6.4) - slower trigger, deeper retracements follow.
- The TAIL cliff starts at 0.5%: NVDA 10y flips from +5,249pp (tick) to
  -15,293pp (0.5% discount) - one missed refill before the 2023 run. Same for
  TSLA. Fast triggers + ANY discount = decade-runaway russian roulette.

## Round B - vol-scaled discounts (roundB.py)

k*ATRp14 or k*sigma20 (frozen at sale), k in 0.25..3, on z50/z150/trail25.
- Same story as fixed discounts once the implied % is similar; no magic from
  vol-adjusting on fast triggers (z50 atr*2: valid +4.69, 10y -53).
- Genuine find: SLOW trigger + small vol unit: z150 atr*0.5 (0/+2.15/10y +21.9,
  NVDA +8,076, TSLA +2,035) and z150 sigma*0.5 (10y +22.6) - best decade medians
  of the whole lab, but valid median only ~+2.2 (no material 2024-26 boost).

## Round C - conditional re-entry + fallback caps (roundC.py)

- "Below sale AND (RSI<40..60 / touch MA20/50 / 10-20d low / 3 calm days)":
  adds NOTHING. For trail25 the conditions are almost always already true when
  price first ticks below sale (identical rows); for z50/z150 they mostly
  degrade (below&touch_ma50: valid +2.64, 10y -22.8). Family rejected.
- Fallback caps on discount rules (force refill after 42/63/126d or when price
  runs +5/10/15% above sale): cap the never-refill tail to ~0-2% BUT destroy
  the edge (z50 d1.5% valid +4.52 -> 0.00 with out>42d, -3.8..-4.4 with
  run+5..15%). Timers buy tops; chases buy breakouts. Confirmed poison.

## Round D - two-tranche ladders, sell-half, vol buckets (roundD.py)

- Ladders (sell all; rebuy w at tick + (1-w) deeper): soften but do not remove
  the tail. Best: z150 L50tick+50@-2% (valid +3.23, 10y +17.7, but NVDA 10y
  -10,844 vs +5,280 tick) and trail25 L70tick+30@-2% (valid +3.62, 10y +7.9,
  ALL FOUR key stocks positive on 10y: TSLA +21/NVDA +6,535/AMZN +82/INTC +79).
- Deep tranches (-8/-10%) kill everything. Sell-half + discount halves the
  damage but NVDA 10y still -11,886 (z50 sellhalf@-2%).
- Vol-bucket triggers (terciles on TUNE-window sigma20; hi-vol rsi80 etc.):
  no improvement over a single trigger anywhere.

## Round E - decaying discounts + bounce-from-low (roundE.py)

- DECAY (demand d0, linearly decays to "tick below" over T days) is the first
  tail-safe median improvement: trail25 decay2%/10d beats trail25-tick on
  EVERY validation window (+3.13/+3.70/+3.40 vs +2.55/+2.84/+2.80) with 10y
  +17.4 and INTC flipped positive (+35..+70); z150 decay2%/10d and decay3%/10d
  beat z150-tick on valid with 10y +19..+21 and TSLA/NVDA still positive.
  z50 decay variants still tail-poisoned (path-dependence: an early discounted
  fill re-times later sales into the runaway).
- BOUNCE (rebuy b% off the low since sale): uncapped = disaster (valid -2..-13,
  buys local tops); capped below sale = flat with 20-37% never-refill. Rejected.

## Round F - 19 finalists x all 7 windows (roundF.py)

Full stats in roundF.json. Rank/robustness summary in BEAT_BH_ROUND2.md.
Key: z50 d2.0% is the max-median rule that still holds the 10y median
(+5.66/+7.32/+7.10 valid5/6/7 = ~2.3pp/yr; 10y +7.34) but all four key stocks
are 10y-catastrophic; trail25 L70tick+30@-2% and trail25/z150 decay2%/10d are
the robust picks (~1.2-1.5pp/yr, 7/7 windows non-negative, live decade tails).

## Round G - hybrids (roundG.py)

- Ladder+decay (e.g. trail25 L50tick+50decay2%/10d): 7/7 non-negative,
  valid ~+3.1-3.6, 10y +13.4 - solid but no better than the simpler parents.
- Combined exit z150|trail25 (any variant): tune/valid fine, 10y median
  -31..-77 with 7-11 sells/window - overtrading kills the decade. Rejected.

Conclusion -> BEAT_BH_ROUND2.md
