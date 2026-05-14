import asyncio

from app.config import Settings
from app.database import Base
from app.models import RefreshRun
from app.refresh import latest_rankings, run_refresh
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_refresh_creates_rankings_with_missing_external_keys(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "portfolio.yml").write_text(
        """
stocks:
  - symbol: AAPL
    name: Apple Inc.
    sector: Technology
    exchange: NASDAQ
""",
        encoding="utf-8",
    )

    settings = Settings(database_url=f"sqlite:///{db_path}", alphavantage_api_key=None, fmp_api_key=None, openai_api_key=None)
    run = asyncio.run(run_refresh(db, settings))
    rows = latest_rankings(db)

    assert run.status == "success"
    assert db.query(RefreshRun).count() == 1
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["category"] in {"strong buy", "buy", "hold", "sell", "strong sell"}
    assert rows[0]["agent_debate"]
