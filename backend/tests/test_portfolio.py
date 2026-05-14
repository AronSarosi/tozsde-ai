from pathlib import Path

from app.portfolio import load_portfolio


def test_load_portfolio_normalizes_symbols(tmp_path: Path):
    path = tmp_path / "portfolio.yml"
    path.write_text(
        """
stocks:
  - symbol: ktos
    name: Kratos Defense
    sector: Industrials
    exchange: NASDAQ
""",
        encoding="utf-8",
    )

    stocks = load_portfolio(path)

    assert stocks[0].symbol == "KTOS"
    assert stocks[0].name == "Kratos Defense"
