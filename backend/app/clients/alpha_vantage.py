from datetime import date, timedelta
import hashlib
import math
import random

import httpx


class AlphaVantageClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    async def daily_prices(self, symbol: str) -> tuple[list[dict], str]:
        if not self.api_key:
            return demo_prices(symbol), "demo_missing_alphavantage_key"

        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "apikey": self.api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return demo_prices(symbol), "demo_alphavantage_error"

        series = payload.get("Time Series (Daily)")
        if not series:
            return demo_prices(symbol), "demo_alphavantage_empty"

        prices = []
        for day, values in series.items():
            prices.append(
                {
                    "date": date.fromisoformat(day),
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "volume": int(values["5. volume"]),
                }
            )
        prices.sort(key=lambda item: item["date"])
        return prices, "alphavantage"


def demo_prices(symbol: str, days: int = 260) -> list[dict]:
    seed = int(hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    base = 18 + (seed % 240)
    drift = rng.uniform(-0.0004, 0.0014)
    volatility = rng.uniform(0.012, 0.04)
    today = date.today()
    price = float(base)
    rows = []
    for idx in range(days):
        day = today - timedelta(days=days - idx)
        if day.weekday() >= 5:
            continue
        seasonal = math.sin(idx / 18) * volatility * 0.5
        ret = drift + seasonal + rng.gauss(0, volatility)
        open_price = price
        close = max(1.0, price * (1 + ret))
        high = max(open_price, close) * (1 + abs(rng.gauss(0, volatility / 2)))
        low = min(open_price, close) * (1 - abs(rng.gauss(0, volatility / 2)))
        volume = int(500_000 + rng.random() * 8_000_000)
        rows.append(
            {
                "date": day,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(max(0.5, low), 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
        price = close
    return rows
