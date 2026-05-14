from datetime import date

import httpx


class FmpClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    async def price_target_consensus(self, symbol: str) -> tuple[dict | None, str]:
        if not self.api_key:
            return None, "missing_fmp_key"

        url = "https://financialmodelingprep.com/stable/price-target-consensus"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, params={"symbol": symbol, "apikey": self.api_key})
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return None, "fmp_error"

        item = payload[0] if isinstance(payload, list) and payload else payload if isinstance(payload, dict) else None
        if not item:
            return None, "fmp_empty"
        return {
            "as_of": date.today(),
            "target_high": _float_or_none(item.get("targetHigh") or item.get("target_high")),
            "target_low": _float_or_none(item.get("targetLow") or item.get("target_low")),
            "target_consensus": _float_or_none(item.get("targetConsensus") or item.get("target_consensus")),
            "target_median": _float_or_none(item.get("targetMedian") or item.get("target_median")),
        }, "fmp"


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
