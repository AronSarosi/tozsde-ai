import asyncio

from app.clients.sec import SecClient


def test_resolve_cik_uses_cached_ticker_map():
    client = SecClient("test@example.com")
    client._ticker_map = {"AAPL": "0000320193"}

    cik, source = asyncio.run(client.resolve_cik("aapl"))

    assert cik == "0000320193"
    assert source == "sec_cik_lookup"
