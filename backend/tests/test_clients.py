import asyncio

from app.clients.alpha_vantage import AlphaVantageClient
from app.clients.fmp import FmpClient
from app.clients.sec import SecClient


def test_alpha_vantage_missing_key_returns_demo_prices():
    prices, source = asyncio.run(AlphaVantageClient(None).daily_prices("AAPL"))

    assert source == "demo_missing_alphavantage_key"
    assert len(prices) > 50


def test_fmp_missing_key_returns_missing_status():
    target, status = asyncio.run(FmpClient(None).price_target_consensus("AAPL"))

    assert target is None
    assert status == "missing_fmp_key"


def test_sec_missing_cik_does_not_fail():
    filings, status = asyncio.run(SecClient("test@example.com").recent_filings(None))

    assert filings == []
    assert status == "missing_cik"
