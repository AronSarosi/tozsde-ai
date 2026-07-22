# Aron-philosophy strategy report

Rules: long-only, buy when price in bottom of trailing range after stabilization,
never sell at a loss, take profit only near relative highs (or pure hold).

BEST (cfg-57): {'lb': 252, 'entry_pos': 0.3, 'stab': 5, 'min_profit': 0.35, 'exit_pos': 2.0}
TRAIN: {'n': 99, 'median_ret': 57.4, 'pct_profitable': 71, 'median_edge': -96.4, 'pct_beat_bh': 14, 'tsla': {'strat': np.float64(533.4), 'bh': np.float64(716.7), 'edge': np.float64(-183.3), 'round_trips': 0, 'realized_losses': 0, 'open_pos_ret': np.float64(533.4), 'worst_open_dd': np.float64(-38.7), 'time_in': 71}}
TEST: {'n': 104, 'median_ret': 48.8, 'pct_profitable': 82, 'median_edge': -2.1, 'pct_beat_bh': 19, 'tsla': {'strat': np.float64(218.8), 'bh': np.float64(250.5), 'edge': np.float64(-31.7), 'round_trips': 0, 'realized_losses': 0, 'open_pos_ret': np.float64(218.8), 'worst_open_dd': 0.0, 'time_in': 99}}

## Best config, TEST window (2023-2026), key stocks

- TSLA: strategy +218.8% vs buy&hold +250.5% | 0 profitable exits, 0 realized losses, worst open drawdown 0.0%, 99% time in market, open pos at +218.8%
- AAPL: strategy +155.0% vs buy&hold +166.5% | 0 profitable exits, 0 realized losses, worst open drawdown 0.0%, 99% time in market, open pos at +155.0%
- MSFT: strategy +70.7% vs buy&hold +70.7% | 0 profitable exits, 0 realized losses, worst open drawdown -7.2%, 100% time in market, open pos at +70.7%
- NVDA: strategy +1308.6% vs buy&hold +1351.3% | 0 profitable exits, 0 realized losses, worst open drawdown -3.3%, 100% time in market, open pos at +1308.6%
- META: strategy +420.7% vs buy&hold +420.7% | 0 profitable exits, 0 realized losses, worst open drawdown 0.0%, 100% time in market, open pos at +420.7%
- GOOGL: strategy +293.0% vs buy&hold +293.0% | 0 profitable exits, 0 realized losses, worst open drawdown -3.3%, 100% time in market, open pos at +293.0%
- AMZN: strategy +188.5% vs buy&hold +188.5% | 0 profitable exits, 0 realized losses, worst open drawdown -3.1%, 100% time in market, open pos at +188.5%
- TSM: strategy +486.0% vs buy&hold +504.1% | 0 profitable exits, 0 realized losses, worst open drawdown -0.8%, 100% time in market, open pos at +486.0%
- MU: strategy +1856.5% vs buy&hold +1856.5% | 0 profitable exits, 0 realized losses, worst open drawdown 0.0%, 100% time in market, open pos at +1856.5%
- INTC: strategy +309.1% vs buy&hold +309.1% | 0 profitable exits, 0 realized losses, worst open drawdown -29.7%, 100% time in market, open pos at +309.1%