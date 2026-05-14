import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, get_db, init_db
from .portfolio import sync_portfolio
from .refresh import latest_rankings, latest_report, run_refresh, stock_detail


settings = get_settings()
app = FastAPI(title="Tőzsde AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
scheduler = BackgroundScheduler(timezone=settings.timezone)


@app.on_event("startup")
def startup() -> None:
    init_db()
    with SessionLocal() as db:
        sync_portfolio(db)
    if not scheduler.running:
        scheduler.add_job(_scheduled_refresh, "cron", hour=settings.refresh_cron_hour, minute=settings.refresh_cron_minute, id="daily-refresh", replace_existing=True)
        scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config/status")
def config_status() -> dict:
    return settings.source_status()


@app.get("/api/portfolio")
def portfolio(db: Session = Depends(get_db)) -> list[dict]:
    stocks = sync_portfolio(db)
    return [
        {
            "symbol": stock.symbol,
            "name": stock.name,
            "sector": stock.sector,
            "exchange": stock.exchange,
            "cik": stock.cik,
        }
        for stock in stocks
    ]


@app.get("/api/rankings/latest")
def rankings(db: Session = Depends(get_db)) -> list[dict]:
    rows = latest_rankings(db)
    if rows:
        return rows
    asyncio.run(run_refresh(db, settings))
    return latest_rankings(db)


@app.get("/api/stocks/{symbol}")
def stock(symbol: str, db: Session = Depends(get_db)) -> dict:
    detail = stock_detail(db, symbol)
    if not detail:
        raise HTTPException(status_code=404, detail="Ticker nem található.")
    return detail


@app.post("/api/refresh")
async def refresh(db: Session = Depends(get_db)) -> dict:
    run = await run_refresh(db, settings)
    return {"run_id": run.id, "status": run.status, "message": run.message}


@app.get("/api/reports/latest")
def report(db: Session = Depends(get_db)) -> dict:
    latest = latest_report(db)
    if latest:
        return latest
    asyncio.run(run_refresh(db, settings))
    latest = latest_report(db)
    if not latest:
        raise HTTPException(status_code=404, detail="Még nincs riport.")
    return latest


def _scheduled_refresh() -> None:
    with SessionLocal() as db:
        asyncio.run(run_refresh(db, settings))
