# Per-stock backtest report

Universe: 99 stocks | TRAIN 2016-07-18..2022-12-31 | TEST ..2026-07-21

BASELINE train: {'n': 99, 'median_ret': 47.3, 'pct_profitable': 78, 'median_edge_vs_bh': -120.7, 'pct_beat_bh': 13} | test: {'n': 104, 'median_ret': 45.3, 'pct_profitable': 79, 'median_edge_vs_bh': -66.4, 'pct_beat_bh': 15}
BEST (rand-67) train: {'n': 99, 'median_ret': 70.3, 'pct_profitable': 79, 'median_edge_vs_bh': -104.0, 'pct_beat_bh': 18} | test: {'n': 104, 'median_ret': 76.1, 'pct_profitable': 81, 'median_edge_vs_bh': -44.0, 'pct_beat_bh': 17}
BEST config: {'w_r3': 0.303, 'w_r6': 0.1, 'w_ma50': 0.387, 'w_ma200': 0.21, 'scale': 80, 'enter_th': 55, 'exit_th': 38, 'trail': -0.25}

## Best config, TEST window, key stocks

- AAPL: strategy +91.1% vs buy&hold +166.5% (edge -75.4pp, 1 trades, 90% time in market)
- MSFT: strategy +40.6% vs buy&hold +70.7% (edge -30.2pp, 1 trades, 89% time in market)
- TSLA: strategy -27.0% vs buy&hold +250.5% (edge -277.5pp, 8 trades, 71% time in market)
- NVDA: strategy +946.4% vs buy&hold +1351.3% (edge -404.9pp, 2 trades, 94% time in market)
- META: strategy +140.8% vs buy&hold +420.7% (edge -279.9pp, 3 trades, 88% time in market)
- GOOGL: strategy +184.6% vs buy&hold +293.0% (edge -108.4pp, 1 trades, 92% time in market)
- AMZN: strategy +83.2% vs buy&hold +188.5% (edge -105.3pp, 1 trades, 93% time in market)
- TSM: strategy +373.8% vs buy&hold +504.1% (edge -130.3pp, 1 trades, 96% time in market)
- MU: strategy +1469.3% vs buy&hold +1856.5% (edge -387.2pp, 4 trades, 78% time in market)
- INTC: strategy +186.5% vs buy&hold +309.1% (edge -122.6pp, 5 trades, 67% time in market)