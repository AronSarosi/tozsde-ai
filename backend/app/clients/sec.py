from datetime import date

import httpx


WATCHED_FORMS = {"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K"}


class SecClient:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self._ticker_map: dict[str, str] | None = None

    async def resolve_cik(self, symbol: str) -> tuple[str | None, str]:
        if self._ticker_map is None:
            url = "https://www.sec.gov/files/company_tickers.json"
            headers = {"User-Agent": self.user_agent}
            try:
                async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    payload = response.json()
            except Exception:
                return None, "sec_cik_lookup_error"
            self._ticker_map = {
                str(item.get("ticker", "")).upper(): str(item.get("cik_str", "")).zfill(10)
                for item in payload.values()
                if item.get("ticker") and item.get("cik_str")
            }
        cik = self._ticker_map.get(symbol.upper())
        return cik, "sec_cik_lookup" if cik else "sec_cik_not_found"

    async def recent_filings(self, cik: str | None) -> tuple[list[dict], str]:
        if not cik:
            return [], "missing_cik"
        normalized = str(cik).zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{normalized}.json"
        headers = {"User-Agent": self.user_agent}
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return [], "sec_error"

        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        filings = []
        for form, filed, accession, document in zip(forms, dates, accessions, docs):
            if form not in WATCHED_FORMS:
                continue
            accession_path = accession.replace("-", "")
            filings.append(
                {
                    "form": form,
                    "filing_date": date.fromisoformat(filed),
                    "accession_number": accession,
                    "report_url": f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/{accession_path}/{document}",
                    "summary": f"{form} filing erkezett: {filed}.",
                }
            )
            if len(filings) >= 8:
                break
        return filings, "sec"
