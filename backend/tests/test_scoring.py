from datetime import date, timedelta

from app.scoring import category_for_score, score_stock


def _prices(start: float = 100.0, step: float = 0.4, days: int = 220):
    today = date.today()
    return [
        {
            "date": today - timedelta(days=days - idx),
            "open": start + idx * step,
            "high": start + idx * step + 1,
            "low": start + idx * step - 1,
            "close": start + idx * step,
            "volume": 1_000_000,
        }
        for idx in range(days)
    ]


def test_category_thresholds():
    assert category_for_score(80) == "strong buy"
    assert category_for_score(65) == "buy"
    assert category_for_score(40) == "hold"
    assert category_for_score(25) == "sell"
    assert category_for_score(24.9) == "strong sell"


def test_score_stock_handles_missing_target_without_zeroing_score():
    result = score_stock("MSFT", _prices(), [], None, "missing_fmp_key")

    assert result.score > 40
    assert "Nincs friss célár/elemzoi konszenzus adat." in result.missing_data
    assert result.components["valuation"] == 50.0


def test_score_stock_rewards_upside_target():
    target = {"target_consensus": 260.0, "target_median": 250.0}
    result = score_stock("MSFT", _prices(start=100, step=0.1), [], target, "fmp")

    assert result.components["valuation"] > 70
    assert result.snapshot["agent_debate"]
