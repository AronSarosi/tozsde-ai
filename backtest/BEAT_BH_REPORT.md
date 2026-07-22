# Beat Buy-and-Hold - lab report (backtest/lab, rounds 1-9)

Question: are there per-stock trading rules that beat buy-and-hold of the SAME
stock over the SAME window - specifically Aron's real TSLA move: sell when
relatively high, rebuy lower?

Method: ~104 stocks (SPY excluded from aggregates), 10y daily closes from
data/tozsde_ai.db. 0.1% per side transaction cost (B&H pays the entry cost too,
so zero trades = exactly B&H). Every strategy starts INVESTED on day 1 of the
window, so entry delay is zero by construction and edge can only come from
round trips - this removes the old degenerate "never enter, match B&H" result.
Walk-forward: tune 2021-07..2023-12, validate 2024-01..2026-07; additionally
6y (3y+3y) and 7y (3.5y+3.5y) proportional splits and the full 10y as sanity
checks (Aron directive: every constant swept, incl. MA lookbacks 50-500d and
window length). Metric: per-stock edge = strategy total return minus B&H total
return in percentage points (pp); aggregates = median edge and % of stocks with
positive edge.

## (a) Did anything robustly beat buy-and-hold?

YES - one family, and only one: "sell into extreme strength or after a deep
peak-drop, then rebuy the FIRST close strictly below your sale price, with no
time limit and no extra discount demand." Every surviving rule is a variant of
this. Median edges are real but modest: +1.5 to +3.5pp per 2.5-year window
(roughly +1pp/year), with 64-75% of stocks beating their own B&H. All ten rules
below have median edge >= 0 on EVERY tune and EVERY validation window (5y, 6y
and 7y splits); ranks 1-10 are also positive on the full 10y.

What did NOT survive: everything that waits for a bigger discount (rebuy 5-15%
lower), every give-up timer (forced rebuy after N days buys tops), classic
trend following at any MA lookback, and vol-regime exits.

## (b) Top 10 rules

Edges in pp vs same-stock B&H. "5y T/V" = tune/valid median edge, "pos" = % of
stocks with positive edge in valid. Sells = median round trips per valid window
(2.5y); Tim = median time in market; all rules rebuy at the first close strictly
below the sale price, no time limit, 0.1%/side costs included.

| # | Rule (precise) | 5y T/V | 6y T/V | 7y T/V | 10y med | pos (V) | TSLA | NVDA | AMZN | INTC | Sells | Tim |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | SELL all when z50 > 2.5 (z50 = (close/SMA50-1) / 252d std of same) | +1.4/+3.4 | +3.3/+3.9 | +6.1/+4.3 | +9.3 | 68% | +19.1 | +90.3 | +9.9 | -155.3 | 4 | 92% |
| 2 | SELL all when close <= 75% of peak close since entry (25% trailing) | +2.5/+2.6 | +3.0/+2.8 | +8.7/+2.8 | +15.3 | 68% | -73.5 | +19.6 | +6.8 | -181.9 | 2.5 | 97% |
| 3 | SELL HALF when close <= 78% of peak since entry (22% trail, half exit) | +1.8/+2.6 | +2.7/+3.0 | +5.8/+3.6 | +9.8 | 70% | -23.7 | -123.2 | +3.4 | -49.0 | 3 | 99% |
| 4 | SELL all when z150 > 3.0 | 0.0/+2.2 | +3.3/+2.5 | +4.9/+2.8 | +18.4 | 70% | +11.6 | +35.7 | +2.3 | -157.3 | 3 | 92% |
| 5 | SELL all when close <= 72% of peak since entry (28% trailing) | +1.3/+2.1 | +1.7/+2.3 | +6.1/+2.1 | +9.5 | 72% | +14.7 | +21.0 | -0.0 | +43.7 | 2 | 98% |
| 6 | SELL all when z100 > 3.0 | 0.0/+1.8 | +1.5/+2.2 | +2.5/+2.5 | +13.8 | 68% | +11.6 | +37.7 | +1.9 | -159.3 | 2.5 | 96% |
| 7 | SELL HALF when close <= 75% of peak since entry (25% trail, half exit) | +1.5/+1.8 | +1.6/+2.2 | +5.4/+2.5 | +10.4 | 69% | -32.9 | +10.1 | +3.4 | -118.6 | 2.5 | 98% |
| 8 | SELL HALF when z200 > 3.0 | 0.0/+1.6 | +2.5/+1.8 | +3.3/+2.0 | +10.8 | 71% | +5.1 | +40.0 | +3.4 | +6.1 | 3 | 95% |
| 9 | SELL HALF when close <= 72% of peak since entry (28% trail, half exit) | +0.8/+1.5 | +1.1/+1.5 | +3.9/+1.5 | +8.5 | 75% | +7.5 | +11.5 | 0.0 | +21.2 | 2 | 99% |
| 10 | SELL all when RSI(14) > 80 | 0.0/+1.3 | +2.2/+1.1 | +3.0/+1.3 | +8.0 | 69% | +33.0 | -307.4 | +2.6 | -43.9 | 2 | 98% |

Notation: zL = (close / SMA(L) - 1) divided by the 252-day rolling std of that
distance; "peak since entry" resets on every rebuy. Half exits sell 50% of the
position and rebuy back to full below the sale price.

Honourable mentions that FAILED the 10y test (recent-window overfits): 20%
trailing stop (valid +3.4 but 10y median -40pp) and RSI>75 (valid +2.5 but 10y
-189pp, TSLA -2374pp). Tighter exits look better on 5y and die on the decade.

Robustness / balance picks: #9 (28% trail, half exit) and #8 (z200 half) are
positive for ALL FOUR key stocks and have the highest pos% - lower median, far
fewer ways to get badly hurt.

## (c) Worst ideas (tested, quantified, rejected)

1. Per-stock trend following - exit below MA, re-enter on reclaim - at EVERY
   lookback 50-500d and buffer 0-5%: valid median -20 to -37pp, 10y median
   -170 to -260pp, only 14-32% of stocks positive. Whipsaw + costs on single
   stocks is fatal (works on indices, not here).
2. Demanding an extra rebuy discount (rebuy only 5-15% below sale): turns
   winners into disasters (10y median -100 to -350pp). The whole edge lives in
   "any tick below the sale price"; greed for a bigger discount misses re-entry
   and then the runaway.
3. Give-up timers (forced rebuy after 10-90 days out): systematically buy back
   at highs; degraded every single grid cell they appeared in.
4. Aggressive overextension selling (z > 1.5-2.0 on any MA): -15 to -34pp in
   the 2024-26 bull; you are permanently underinvested in strong trends.
5. Vol-regime exits (20d vol > 1.5-2.5x its 126/252/504d median): flat to -9pp
   valid, -50 to -77pp 10y. One tune-window star (+9.1) collapsed to -29.4 in
   valid - textbook overfit.
6. Upside give-up (chase back in if price breaks +20..50% above sale): caps the
   worst tails but shaves the median in every window; a variance tool, not an
   edge.

## (d) Honest conclusion

- The edge exists, is directionally consistent (10 rules x 7 windows, all
  non-negative, ~2/3 of stocks positive), and is SMALL at the median: about
  +1 to +4pp per 2.5y window vs B&H. It is a skim, not a doubling.
- The dispersion dwarfs the median: single-stock outcomes range from +90pp
  (NVDA, rule 1 valid) to -300pp (NVDA, RSI rule). The one failure mode is
  always the same: you sell, the stock V-recovers without ever closing below
  your sale price, and you watch a runaway from the sidelines. Wide exits,
  half exits and the strictly-below rebuy all exist to shrink that tail.
- Costs matter: 0.1%/side with 2-4 round trips per 2.5y costs ~0.5-1.5pp,
  roughly half the raw edge. A retail spread/slippage above that erases it.
- For a system whose value-add is entry/exit timing, the honest pitch is NOT
  "we beat buy-and-hold by a lot". It is: (1) sell into statistically extreme
  strength (z-score > 2.5-3 on a 50-150d MA, or RSI > 80 on momentum names),
  (2) always rebuy the first dip below your sale - never demand a discount,
  never use a deadline, (3) prefer half positions so being wrong is survivable,
  (4) expect to match B&H most of the time and harvest a few pp when spikes
  mean-revert. That is exactly the shape of Aron's real TSLA trade, and the
  data says it generalizes - modestly - to about two thirds of stocks.
- Everything "protective" (trend exits, vol exits, waiting for pullbacks)
  reliably LOSES to holding, after costs, on individual stocks.

## (e) TSLA highlight - best rule found for TSLA

SELL 100% when RSI(14) > 80; REBUY at the first close strictly below the sale
price, no time limit (0.1%/side):
  tune +11.6pp, valid +33.0pp, full 5y +57.7pp, full 10y +1,717.8pp vs B&H,
  ~4 sales per 2.5y window, ~98% time in market.
Runner-up (same idea, mechanical z-score): SELL when z100 > 2.5, rebuy below
sale: +7.9 / +22.1 / +38.1 / +1,806.5pp.

Why it works on TSLA specifically: TSLA's blow-off spikes reliably retrace.
The z50>2.5 trace sold 2021-10-29 at $371 (eleven days before the all-time-high
area) and rebought 2021-11-09 at $341; in the Nov-Dec 2024 melt-up it sold three
times ($321, $339, $389) and rebought lower each time. TSLA is the ideal client
for this family; the anti-client is 2023-24 NVDA, where RSI>80 stayed pinned
and the stock never looked back (-307pp on that rule).

Artifacts: round scripts + running log in backtest/lab/ (round1..round9,
LOG.md, common.py engine; results JSONs per round).
