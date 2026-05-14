from datetime import datetime
import json

from sqlalchemy.orm import Session

from .ai import build_report, build_stock_summary
from .clients.alpha_vantage import AlphaVantageClient
from .clients.fmp import FmpClient
from .clients.sec import SecClient
from .config import Settings
from .models import AnalystTarget, Filing, PriceDaily, Ranking, RefreshRun, Report, Signal, Stock
from .portfolio import sync_portfolio
from .scoring import dumps, score_stock


async def run_refresh(db: Session, settings: Settings) -> RefreshRun:
    run = RefreshRun(status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        stocks = sync_portfolio(db)
        alpha = AlphaVantageClient(settings.alphavantage_api_key)
        fmp = FmpClient(settings.fmp_api_key)
        sec = SecClient(settings.sec_user_agent)
        ranking_payloads: list[dict] = []

        for stock in stocks:
            prices, price_source = await alpha.daily_prices(stock.symbol)
            _upsert_prices(db, stock, prices, price_source)

            cik_lookup_source = "configured_cik" if stock.cik else "not_needed"
            if not stock.cik:
                resolved_cik, cik_lookup_source = await sec.resolve_cik(stock.symbol)
                if resolved_cik:
                    stock.cik = resolved_cik
                    db.add(stock)
                    db.commit()

            filings, filing_source = await sec.recent_filings(stock.cik)
            _upsert_filings(db, stock, filings)

            target, target_status = await fmp.price_target_consensus(stock.symbol)
            _insert_target(db, stock, target, target_status)

            stored_prices = _price_dicts(db, stock)
            stored_filings = _filing_dicts(db, stock)
            score = score_stock(stock.symbol, stored_prices, stored_filings, target, target_status)
            score.snapshot["price_source"] = price_source
            score.snapshot["filing_source"] = filing_source
            score.snapshot["cik_lookup_source"] = cik_lookup_source

            db.add(
                Signal(
                    stock_id=stock.id,
                    run_id=run.id,
                    momentum_score=score.components["momentum"],
                    fundamentals_score=score.components["fundamentals"],
                    valuation_score=score.components["valuation"],
                    events_score=score.components["events"],
                    risk_score=score.components["risk"],
                    missing_data=dumps(score.missing_data),
                    snapshot_json=dumps(score.snapshot),
                )
            )
            ai_summary = build_stock_summary(settings.openai_api_key, score.snapshot, score.reasons, score.risks)
            db.add(
                Ranking(
                    stock_id=stock.id,
                    run_id=run.id,
                    score=score.score,
                    category=score.category,
                    reasons_json=dumps(score.reasons),
                    risks_json=dumps(score.risks),
                    ai_summary=ai_summary,
                )
            )
            ranking_payloads.append(
                {
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "sector": stock.sector,
                    "score": score.score,
                    "category": score.category,
                    "reasons": score.reasons,
                    "risks": score.risks,
                    "missing_data": score.missing_data,
                    "components": score.components,
                    "agent_debate": score.snapshot.get("agent_debate", []),
                }
            )
            db.commit()

        ranking_payloads.sort(key=_action_sort_key, reverse=True)
        report = build_report(settings.openai_api_key, ranking_payloads)
        db.add(Report(run_id=run.id, content=report, input_snapshot_json=json.dumps(ranking_payloads, ensure_ascii=False, default=str)))
        run.status = "success"
        run.finished_at = datetime.utcnow()
        run.message = f"{len(stocks)} ticker frissitve."
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.message = str(exc)
        db.commit()
        db.refresh(run)
        return run


def latest_rankings(db: Session) -> list[dict]:
    run = db.query(RefreshRun).filter(RefreshRun.status == "success").order_by(RefreshRun.finished_at.desc()).first()
    if not run:
        return []
    rows = (
        db.query(Ranking, Stock, Signal)
        .join(Stock, Stock.id == Ranking.stock_id)
        .outerjoin(Signal, (Signal.stock_id == Ranking.stock_id) & (Signal.run_id == Ranking.run_id))
        .filter(Ranking.run_id == run.id)
        .order_by(Ranking.score.desc())
        .all()
    )
    payloads = [_ranking_payload(ranking, stock, run, signal) for ranking, stock, signal in rows]
    return sorted(payloads, key=_action_sort_key, reverse=True)


def stock_detail(db: Session, symbol: str) -> dict | None:
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not stock:
        return None
    prices = _price_dicts(db, stock)
    filings = _filing_dicts(db, stock)
    ranking_row = (
        db.query(Ranking, RefreshRun, Signal)
        .join(RefreshRun, RefreshRun.id == Ranking.run_id)
        .outerjoin(Signal, (Signal.stock_id == Ranking.stock_id) & (Signal.run_id == Ranking.run_id))
        .filter(Ranking.stock_id == stock.id, RefreshRun.status == "success")
        .order_by(Ranking.created_at.desc())
        .first()
    )
    ranking = _ranking_payload(ranking_row[0], stock, ranking_row[1], ranking_row[2]) if ranking_row else None
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "sector": stock.sector,
        "exchange": stock.exchange,
        "cik": stock.cik,
        "prices": prices[-120:],
        "filings": filings[:10],
        "ranking": ranking,
    }


def latest_report(db: Session) -> dict | None:
    report = db.query(Report).order_by(Report.created_at.desc()).first()
    if not report:
        return None
    return {"created_at": report.created_at, "content": report.content, "input_snapshot": json.loads(report.input_snapshot_json)}


def _upsert_prices(db: Session, stock: Stock, prices: list[dict], source: str) -> None:
    existing = {row.date: row for row in db.query(PriceDaily).filter(PriceDaily.stock_id == stock.id).all()}
    for item in prices:
        row = existing.get(item["date"])
        if row is None:
            row = PriceDaily(stock_id=stock.id, date=item["date"], open=item["open"], high=item["high"], low=item["low"], close=item["close"], volume=item["volume"], source=source)
            db.add(row)
        else:
            row.open = item["open"]
            row.high = item["high"]
            row.low = item["low"]
            row.close = item["close"]
            row.volume = item["volume"]
            row.source = source


def _upsert_filings(db: Session, stock: Stock, filings: list[dict]) -> None:
    existing = {row.accession_number for row in db.query(Filing).filter(Filing.stock_id == stock.id).all()}
    for item in filings:
        if item["accession_number"] in existing:
            continue
        db.add(
            Filing(
                stock_id=stock.id,
                form=item["form"],
                filing_date=item["filing_date"],
                accession_number=item["accession_number"],
                report_url=item.get("report_url"),
                summary=item.get("summary"),
            )
        )


def _insert_target(db: Session, stock: Stock, target: dict | None, status: str) -> None:
    if not target:
        db.add(AnalystTarget(stock_id=stock.id, as_of=datetime.utcnow().date(), source=status))
        return
    db.add(
        AnalystTarget(
            stock_id=stock.id,
            as_of=target["as_of"],
            target_high=target.get("target_high"),
            target_low=target.get("target_low"),
            target_consensus=target.get("target_consensus"),
            target_median=target.get("target_median"),
            source=status,
        )
    )


def _price_dicts(db: Session, stock: Stock) -> list[dict]:
    rows = db.query(PriceDaily).filter(PriceDaily.stock_id == stock.id).order_by(PriceDaily.date.asc()).all()
    return [{"date": row.date, "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume, "source": row.source} for row in rows]


def _filing_dicts(db: Session, stock: Stock) -> list[dict]:
    rows = db.query(Filing).filter(Filing.stock_id == stock.id).order_by(Filing.filing_date.desc()).all()
    return [{"form": row.form, "filing_date": row.filing_date, "accession_number": row.accession_number, "report_url": row.report_url, "summary": row.summary} for row in rows]


def _ranking_payload(ranking: Ranking, stock: Stock, run: RefreshRun, signal: Signal | None) -> dict:
    signal_data = db_signal_safe(signal)
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "sector": stock.sector,
        "exchange": stock.exchange,
        "score": ranking.score,
        "category": ranking.category,
        "reasons": json.loads(ranking.reasons_json),
        "risks": json.loads(ranking.risks_json),
        "ai_summary": ranking.ai_summary,
        "components": signal_data.get("components", {}),
        "missing_data": signal_data.get("missing_data", []),
        "agent_debate": signal_data.get("agent_debate", []),
        "run_id": run.id,
        "run_finished_at": run.finished_at,
    }


def db_signal_safe(signal: Signal | None) -> dict:
    if not signal:
        return {"components": {}, "missing_data": [], "agent_debate": []}
    snapshot = json.loads(signal.snapshot_json) if signal.snapshot_json else {}
    return {
        "components": {
            "momentum": signal.momentum_score,
            "fundamentals": signal.fundamentals_score,
            "valuation": signal.valuation_score,
            "events": signal.events_score,
            "risk": signal.risk_score,
        },
        "missing_data": json.loads(signal.missing_data),
        "agent_debate": snapshot.get("agent_debate", []),
    }


def _action_sort_key(item: dict) -> tuple[int, float, float]:
    priority = {"strong buy": 5, "strong sell": 5, "buy": 4, "sell": 4, "hold": 1}
    score = float(item.get("score") or 0)
    return (priority.get(item.get("category"), 0), abs(score - 50), score)
