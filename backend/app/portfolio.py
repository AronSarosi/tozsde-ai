from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import Stock


class PortfolioStock(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    name: str
    sector: str = "Unknown"
    exchange: str = "Unknown"
    cik: str | None = None


def load_portfolio(path: str | Path = "portfolio.yml") -> list[PortfolioStock]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    stocks = raw.get("stocks", [])
    return [
        PortfolioStock(
            symbol=str(item["symbol"]).upper().strip(),
            name=str(item["name"]).strip(),
            sector=str(item.get("sector", "Unknown")).strip(),
            exchange=str(item.get("exchange", "Unknown")).strip(),
            cik=str(item["cik"]).strip() if item.get("cik") else None,
        )
        for item in stocks
    ]


def sync_portfolio(db: Session, path: str | Path = "portfolio.yml") -> list[Stock]:
    items = load_portfolio(path)
    existing = {stock.symbol: stock for stock in db.query(Stock).all()}
    synced: list[Stock] = []
    for item in items:
        stock = existing.get(item.symbol)
        if stock is None:
            stock = Stock(symbol=item.symbol, name=item.name, sector=item.sector, exchange=item.exchange, cik=item.cik)
            db.add(stock)
        else:
            stock.name = item.name
            stock.sector = item.sector
            stock.exchange = item.exchange
            stock.cik = item.cik
        synced.append(stock)
    db.commit()
    for stock in synced:
        db.refresh(stock)
    return synced
