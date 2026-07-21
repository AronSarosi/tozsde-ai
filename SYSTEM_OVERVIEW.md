# Tozsde AI - System Overview (v2, July 2026)

## How the system works

Two layers:

**1. Daily engine - `pipeline.py` (runs locally, scheduled weekdays 22:15)**

- Downloads daily OHLCV prices for the 104-stock universe + SPY from Yahoo Finance into SQLite (`data/tozsde_ai.db`, ~52k rows of 2-year history).
- Fetches fundamentals (~30 fields per stock: margins, growth, cash flow, analyst targets, etc.) and recent news headlines with keyword sentiment.
- Computes the v2 score for every stock (see below), books the shadow portfolio's daily trades, marks everything to market.
- Exports two small JSON snapshots into `snapshot/` (git-tracked) and pushes them, so the Vercel site always shows the latest run.

**2. Serving layer - `run_local.py` + `frontend_light.html` (local + Vercel)**

- Same stdlib-only server as before. It still fetches live quotes for display, but scores/tiers/targets now come from the committed snapshot (overlay in `build_state`). `/api/shadow` serves the shadow portfolio snapshot.

## Scoring (WarrenAI-inspired, deterministic)

Eight factors, each expressed as a cross-sectional percentile (0-100) against the whole universe:
momentum (18%), analyst view (18%), growth (14%), value (12%), risk (12%), profitability (10%), cash flow (8%), news sentiment (8%).

- **Composite score 0-100** = 45% absolute blend + 55% universe rank, so scores actually spread out.
- **5 tiers**: top 10% = Eros vetel (strong buy), next 20% = Vetel, middle 40% = Tartas, next 20% = Eladas, bottom 10% = Eros eladas.
- **Financial health 1-5** (like InvestingPro): mean of 5 sub-scores - relative value, momentum, cash flow, profitability, growth.
- **Fair value** = average of up to 3 models (analyst consensus target, peer forward-P/E multiple, DCF-lite on free cash flow), clamped to 0.4x-2.5x price. Produces % upside + label (Alulertekelt / Korrekt arazas / Tulertekelt).
- **ProTips-style bullets** + bull/bear cases generated from the factor extremes.

## Shadow portfolio (the live test)

Started **2026-07-17** (first trading day booked). Rules:

- Every trading day: $1,000 hypothetical into each of the **5 strongest signals** (long for buys, short for sells), ranked by conviction.
- Exits: longs have NO profit cap and NO time limit (winners run for months/years) - exit only at -10% stop or when the signal flips to sell. Shorts: -15% target / +10% stop or signal flip.
- Benchmark: $5,000/day into SPY - the strategy must beat simple indexing to be worth anything.
- UI: "Portfolio" button top-right opens a broker-style drawer (positions, P&L, daily batch, closed trades, vs-SPY alpha).
- State lives in SQLite (`shadow_lots`, `shadow_batches`, `benchmark_lots`) + `snapshot/shadow_state.json`.

## vs Investing.com WarrenAI

| Feature | WarrenAI / InvestingPro | Tozsde AI v2 |
|---|---|---|
| Fair value | 17-model ensemble | 3-model ensemble (analyst, multiple, DCF-lite) |
| Health score | 1-5, five sub-scores | same structure, universe-relative |
| ProTips | pre-computed bullets | generated from factor extremes |
| AI portfolio | ProPicks: monthly rebalanced baskets, backtested on Vertex AI | daily top-5 conviction shadow portfolio, live tracked vs SPY |
| Data freshness | real-time, 72k+ assets | daily close + live quotes, 104 curated AI/chip/cyber-focused stocks |
| Q&A chat | credit-metered LLM chat | not wired (endpoint exists, UI removed) |

Their edge is data breadth and real-time feeds; our edge is transparency (every score decomposable), zero cost, and a live honest track record from day one.

## Operations

- `python pipeline.py init` - one-time backfill (already done)
- `python pipeline.py daily` - full daily run (idempotent; scheduled task "TozsdeAI Daily" runs it weekdays 22:15 and pushes snapshots)
- `python pipeline.py status` - DB row counts
- `python run_local.py` - local dashboard at http://127.0.0.1:8000
- Remove automation: `schtasks /Delete /TN "TozsdeAI Daily"`
