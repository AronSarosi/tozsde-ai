"""Tozsde AI v2 data pipeline.

Local daily engine (NOT deployed to Vercel):
  python pipeline.py init    -- create DB + backfill 2 years of daily prices
  python pipeline.py daily   -- incremental update: prices, fundamentals, news,
                                v2 scores, shadow portfolio batch, snapshots
  python pipeline.py status  -- quick DB/state summary

Persists everything in data/tozsde_ai.db (SQLite, gitignored) and exports two
small JSON snapshots into snapshot/ (git-tracked, deployed to Vercel):
  snapshot/daily_state.json   -- per-stock v2 scores, health, fair value, tips
  snapshot/shadow_state.json  -- shadow portfolio (daily $1000 x top-5 signals)

Dependencies (local only): yfinance, pandas. run_local.py stays stdlib-only.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = ROOT / "snapshot"
DB_PATH = DATA_DIR / "tozsde_ai.db"
PORTFOLIO_FILE = ROOT / "portfolio.yml"

BENCHMARK = "SPY"
HISTORY_YEARS = 10

# Shadow portfolio rules
LOT_SIZE_USD = 1000.0
DAILY_PICKS = 5
# Longs NEVER realize a loss (Aron's rule, backtest-confirmed): an underwater
# long is held - for years if needed - until profitable. Exit only when the
# position is in profit AND the signal has flipped to sell.
SHORT_MAX_SCORE = 25  # shorts only on extreme conviction (rare by design)
SHORT_TARGET = 0.15   # price falls 15% -> take profit on short
SHORT_STOP = -0.10    # short moves 10% against us -> stop out

TIER_LABELS_HU = {
    "strong_buy": "Erős vétel",
    "buy": "Vétel",
    "hold": "Tartás",
    "sell": "Eladás",
    "strong_sell": "Erős eladás",
}

POSITIVE_WORDS = [
    "beat", "beats", "record", "surge", "surges", "soar", "soars", "upgrade",
    "upgrades", "raises", "raised", "growth", "wins", "win", "partnership",
    "buyback", "strong", "tops", "outperform", "rally", "breakthrough",
    "expands", "accelerat", "profit jump", "guidance rais",
]
NEGATIVE_WORDS = [
    "miss", "misses", "cuts", "cut", "downgrade", "downgrades", "lawsuit",
    "probe", "falls", "fall", "drops", "plunge", "plunges", "layoff",
    "layoffs", "warning", "warns", "weak", "recall", "investigation", "slump",
    "guidance cut", "underperform", "fraud", "delay", "halts",
]


# ---------------------------------------------------------------- utilities

def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def load_universe() -> list[dict]:
    import re
    text = PORTFOLIO_FILE.read_text(encoding="utf-8")
    blocks = re.findall(
        r"  - symbol: (\S+)\n    name: (.+)\n    sector: (.+)\n    exchange: (\S+)", text
    )
    return [
        {"symbol": s, "name": n.strip(), "sector": sec.strip(), "exchange": ex}
        for s, n, sec, ex in blocks
    ]


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS prices_daily (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (symbol, date)
        );
        CREATE TABLE IF NOT EXISTS fundamentals (
            symbol TEXT PRIMARY KEY,
            updated_at TEXT,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, published_at TEXT, title TEXT, publisher TEXT,
            url TEXT UNIQUE, sentiment REAL
        );
        CREATE TABLE IF NOT EXISTS scores (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            score REAL, tier TEXT, conviction REAL,
            health REAL, fair_value REAL, upside REAL, valuation_label TEXT,
            payload TEXT,
            PRIMARY KEY (symbol, date)
        );
        CREATE TABLE IF NOT EXISTS shadow_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_date TEXT, symbol TEXT, side TEXT,
            entry_price REAL, qty REAL, invested REAL,
            status TEXT DEFAULT 'open',
            exit_date TEXT, exit_price REAL, exit_reason TEXT, pnl REAL
        );
        CREATE TABLE IF NOT EXISTS shadow_batches (
            date TEXT PRIMARY KEY,
            picks TEXT
        );
        CREATE TABLE IF NOT EXISTS shadow_rebuys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, sale_date TEXT, sale_price REAL, amount REAL,
            status TEXT DEFAULT 'pending', filled_date TEXT, filled_price REAL
        );
        CREATE TABLE IF NOT EXISTS benchmark_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_date TEXT, entry_price REAL, qty REAL, invested REAL
        );
        """
    )
    con.commit()


# ---------------------------------------------------------------- price data

def upsert_prices(con: sqlite3.Connection, symbol: str, frame: pd.DataFrame) -> int:
    rows = 0
    for idx, row in frame.iterrows():
        close = row.get("Close")
        if close is None or (isinstance(close, float) and math.isnan(close)):
            continue
        d = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        con.execute(
            "INSERT OR REPLACE INTO prices_daily (symbol, date, open, high, low, close, volume)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                symbol,
                d,
                _f(row.get("Open")), _f(row.get("High")), _f(row.get("Low")),
                _f(close), int(_f(row.get("Volume")) or 0),
            ),
        )
        rows += 1
    return rows


def _f(v):
    try:
        v = float(v)
        return None if math.isnan(v) else round(v, 4)
    except (TypeError, ValueError):
        return None


def fetch_prices(con: sqlite3.Connection, symbols: list[str], full: bool) -> None:
    tickers = [yahoo_symbol(s) for s in symbols] + [BENCHMARK]
    period = f"{HISTORY_YEARS}y" if full else "10d"
    print(f"Downloading {'full ' + period if full else 'incremental'} prices for {len(tickers)} tickers...")
    data = yf.download(
        tickers=" ".join(tickers), period=period, interval="1d",
        group_by="ticker", auto_adjust=True, threads=True, progress=False,
    )
    mapping = {yahoo_symbol(s): s for s in symbols}
    mapping[BENCHMARK] = BENCHMARK
    total = 0
    for ysym, canonical in mapping.items():
        try:
            frame = data[ysym].dropna(how="all")
        except KeyError:
            print(f"  WARN no price data for {canonical}")
            continue
        total += upsert_prices(con, canonical, frame)
    con.commit()
    print(f"  upserted {total} price rows")


def price_series(con: sqlite3.Connection, symbol: str, limit: int = 550) -> list[dict]:
    cur = con.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily"
        " WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (symbol, limit),
    )
    return [dict(r) for r in reversed(cur.fetchall())]


def latest_trading_date(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT MAX(date) AS d FROM prices_daily WHERE symbol=?", (BENCHMARK,)).fetchone()
    return row["d"]


# ------------------------------------------------------------- fundamentals

FUND_FIELDS = [
    "marketCap", "trailingPE", "forwardPE", "forwardEps", "trailingEps",
    "priceToSalesTrailing12Months", "profitMargins", "grossMargins",
    "operatingMargins", "returnOnEquity", "revenueGrowth", "earningsGrowth",
    "freeCashflow", "operatingCashflow", "totalCash", "totalDebt",
    "debtToEquity", "beta", "targetMeanPrice", "targetHighPrice",
    "targetLowPrice", "numberOfAnalystOpinions", "recommendationKey",
    "recommendationMean", "dividendYield", "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow", "currentPrice", "sharesOutstanding",
]


def fetch_fundamentals(con: sqlite3.Connection, universe: list[dict], max_age_hours: float = 20.0) -> None:
    now = datetime.now()
    stale: list[str] = []
    for stock in universe:
        row = con.execute("SELECT updated_at FROM fundamentals WHERE symbol=?", (stock["symbol"],)).fetchone()
        if row and row["updated_at"]:
            age = now - datetime.fromisoformat(row["updated_at"])
            if age < timedelta(hours=max_age_hours):
                continue
        stale.append(stock["symbol"])
    if not stale:
        print("Fundamentals fresh, skipping.")
        return
    print(f"Fetching fundamentals for {len(stale)} tickers (throttled)...")
    for i, symbol in enumerate(stale, 1):
        try:
            info = yf.Ticker(yahoo_symbol(symbol)).info or {}
            payload = {k: info.get(k) for k in FUND_FIELDS}
            con.execute(
                "INSERT OR REPLACE INTO fundamentals (symbol, updated_at, data) VALUES (?,?,?)",
                (symbol, now.isoformat(timespec="seconds"), json.dumps(payload)),
            )
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            print(f"  WARN fundamentals {symbol}: {exc}")
        if i % 20 == 0:
            con.commit()
            print(f"  {i}/{len(stale)}")
        time.sleep(0.25)
    con.commit()


def fetch_news(con: sqlite3.Connection, universe: list[dict]) -> None:
    print("Fetching news headlines...")
    added = 0
    for stock in universe:
        try:
            items = yf.Ticker(yahoo_symbol(stock["symbol"])).news or []
        except Exception:
            continue
        for item in items[:10]:
            content = item.get("content") or item
            title = content.get("title") or ""
            if not title:
                continue
            url = ((content.get("canonicalUrl") or {}).get("url")
                   if isinstance(content.get("canonicalUrl"), dict)
                   else content.get("link") or content.get("url") or "")
            pub = content.get("pubDate") or content.get("displayTime") or ""
            if str(pub).isdigit():  # epoch seconds -> ISO so string date comparisons work
                pub = datetime.fromtimestamp(int(str(pub))).isoformat()
            provider = content.get("provider") or {}
            publisher = provider.get("displayName") if isinstance(provider, dict) else str(provider or "")
            try:
                con.execute(
                    "INSERT OR IGNORE INTO news (symbol, published_at, title, publisher, url, sentiment)"
                    " VALUES (?,?,?,?,?,?)",
                    (stock["symbol"], str(pub)[:19], title, publisher or "", url, headline_sentiment(title)),
                )
                added += con.execute("SELECT changes()").fetchone()[0]
            except sqlite3.Error:
                continue
        time.sleep(0.1)
    con.commit()
    print(f"  {added} new headlines stored")


def headline_sentiment(title: str) -> float:
    low = title.lower()
    score = 0.0
    for w in POSITIVE_WORDS:
        if w in low:
            score += 1.0
    for w in NEGATIVE_WORDS:
        if w in low:
            score -= 1.0
    return max(-2.0, min(2.0, score))


# ------------------------------------------------------------------ scoring

def _ramp(x: float | None, x0: float, y0: float, x1: float, y1: float) -> float | None:
    """Piecewise-linear map of x from [x0,x1] to [y0,y1], clamped at the ends."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if x <= x0:
        return float(y0)
    if x >= x1:
        return float(y1)
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def pct_rank(values: dict[str, float | None]) -> dict[str, float]:
    """Cross-sectional percentile rank 0..100; missing values -> 50 (neutral)."""
    present = {k: v for k, v in values.items() if v is not None and not (isinstance(v, float) and math.isnan(v))}
    out = {k: 50.0 for k in values}
    if len(present) < 3:
        return out
    ordered = sorted(present.items(), key=lambda kv: kv[1])
    n = len(ordered)
    for i, (k, _) in enumerate(ordered):
        out[k] = round(100.0 * i / (n - 1), 1)
    return out


def load_env_file() -> dict[str, str]:
    vals: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def llm_news_scores(con: sqlite3.Connection, universe: list[dict], api_key: str | None,
                    model: str = "gpt-4o-mini") -> dict[str, dict]:
    """LLM reads each stock's recent headlines: sentiment -2..+2 + short reason,
    plus any explicit analyst price targets mentioned. Deterministic (temp 0).
    Returns {} without a key; caller falls back to keyword sentiment."""
    if not api_key:
        return {}
    import urllib.request as ur
    cutoff = (datetime.now() - timedelta(days=14)).isoformat()[:19]
    per_sym: dict[str, list[str]] = {}
    for stock in universe:
        rows = con.execute(
            "SELECT title FROM news WHERE symbol=? AND published_at>=?"
            " ORDER BY published_at DESC LIMIT 6",
            (stock["symbol"], cutoff),
        ).fetchall()
        if rows:
            per_sym[stock["symbol"]] = [r["title"] for r in rows]
    out: dict[str, dict] = {}
    syms = list(per_sym)
    print(f"LLM news scoring for {len(syms)} tickers...")
    system_prompt = (
        "You are a financial news analyst. For each ticker, rate the aggregate stock-relevant"
        " sentiment of its recent headlines on an integer scale -2..+2 (-2 clearly negative,"
        " -1 mildly negative, 0 neutral or mixed, 1 mildly positive, 2 clearly positive)."
        " Also extract any explicit analyst price targets mentioned in the headlines as"
        " {firm, target}. Reply with strict JSON:"
        " {\"TICKER\": {\"s\": int, \"r\": \"reason, max 12 words, in Hungarian\","
        " \"t\": [{\"firm\": str, \"target\": number}]}} covering every ticker given. No other keys."
    )
    for i in range(0, len(syms), 15):
        batch = syms[i:i + 15]
        lines = [f"{s}: " + " || ".join(per_sym[s]) for s in batch]
        body = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "\n".join(lines)},
            ],
        }
        req = ur.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            resp = json.load(ur.urlopen(req, timeout=180))
            parsed = json.loads(resp["choices"][0]["message"]["content"])
            for sym, v in parsed.items():
                if isinstance(v, dict) and isinstance(v.get("s"), (int, float)):
                    out[sym.upper()] = {
                        "s": max(-2, min(2, int(v["s"]))),
                        "r": str(v.get("r") or "")[:160],
                        "t": [t for t in (v.get("t") or [])
                              if isinstance(t, dict) and isinstance(t.get("target"), (int, float))][:5],
                    }
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN LLM batch {i // 15 + 1} failed: {exc}")
    print(f"  scored {len(out)} tickers via LLM")
    return out


def fetch_analyst_actions(con: sqlite3.Connection, universe: list[dict]) -> None:
    """Recent analyst rating actions (firm, upgrade/downgrade, grades) per stock."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS analyst_actions (symbol TEXT, date TEXT, firm TEXT,"
        " action TEXT, from_grade TEXT, to_grade TEXT, PRIMARY KEY (symbol, date, firm))"
    )
    print("Fetching analyst rating actions...")
    for stock in universe:
        sym = stock["symbol"]
        try:
            df = yf.Ticker(yahoo_symbol(sym)).upgrades_downgrades
            if df is None or df.empty:
                continue
            for idx, row in df.head(12).iterrows():
                d = str(idx)[:10]
                con.execute(
                    "INSERT OR REPLACE INTO analyst_actions (symbol, date, firm, action, from_grade, to_grade)"
                    " VALUES (?,?,?,?,?,?)",
                    (sym, d, str(row.get("Firm") or ""), str(row.get("Action") or ""),
                     str(row.get("FromGrade") or ""), str(row.get("ToGrade") or "")),
                )
        except Exception:
            continue
        time.sleep(0.12)
    con.commit()


def load_analyst_actions(con: sqlite3.Connection) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    try:
        cur = con.execute(
            "SELECT symbol, date, firm, action, from_grade, to_grade FROM analyst_actions"
            " ORDER BY date DESC"
        )
    except sqlite3.Error:
        return out
    for r in cur.fetchall():
        lst = out.setdefault(r["symbol"], [])
        if len(lst) < 8:
            lst.append({"date": r["date"], "firm": r["firm"], "action": r["action"],
                        "from": r["from_grade"], "to": r["to_grade"]})
    return out


def compute_scores(con: sqlite3.Connection, universe: list[dict],
                   llm_news: dict[str, dict] | None = None) -> dict:
    as_of = latest_trading_date(con)
    if not as_of:
        raise SystemExit("No benchmark price data in DB (SPY download failed) - aborting run.")
    analyst_actions = load_analyst_actions(con)
    llm_news = llm_news or {}
    fundamentals: dict[str, dict] = {}
    for stock in universe:
        row = con.execute("SELECT data FROM fundamentals WHERE symbol=?", (stock["symbol"],)).fetchone()
        fundamentals[stock["symbol"]] = json.loads(row["data"]) if row and row["data"] else {}

    series: dict[str, list[dict]] = {}
    raw: dict[str, dict[str, float | None]] = {}
    factor_names = ["momentum", "value", "growth", "profitability", "cashflow", "risk", "analyst", "news"]
    per_factor: dict[str, dict[str, float | None]] = {f: {} for f in factor_names}

    cutoff_news = (datetime.now() - timedelta(days=14)).isoformat()[:19]

    for stock in universe:
        sym = stock["symbol"]
        rows = price_series(con, sym)
        series[sym] = rows
        closes = [r["close"] for r in rows if r["close"]]
        f = fundamentals[sym]
        r: dict[str, float | None] = {}
        if len(closes) >= 60:
            last = closes[-1]
            ma50 = sum(closes[-50:]) / 50
            ma200 = sum(closes[-200:]) / min(200, len(closes))
            ret_3m = last / closes[-63] - 1 if len(closes) >= 63 else None
            ret_6m = last / closes[-126] - 1 if len(closes) >= 126 else None
            mom_raw = ((ret_3m or 0) * 0.4 + (ret_6m or 0) * 0.3
                       + (last / ma50 - 1) * 0.15 + (last / ma200 - 1) * 0.15)
            r["momentum"] = _ramp(mom_raw, -0.40, 5, 0.50, 95)  # 0% momentum ~ 45
            rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - 60), len(closes))]
            vol = (sum((x - sum(rets) / len(rets)) ** 2 for x in rets) / len(rets)) ** 0.5 if rets else None
            peak = max(closes[-252:]) if closes else None
            dd = last / peak - 1 if peak else 0
            r["risk"] = _mean_opt([
                _ramp(-(vol or 0.03), -0.05, 12, -0.008, 88),   # daily vol 0.8% -> 88, 5% -> 12
                _ramp(dd, -0.45, 15, 0.0, 85),                   # drawdown from 1y peak
            ])
        else:
            r["momentum"] = None
            r["risk"] = None

        mcap = f.get("marketCap")
        fpe = f.get("forwardPE")
        earn_yield = (1.0 / fpe) if fpe and fpe > 0 else None
        fcf = f.get("freeCashflow")
        fcf_yield = (fcf / mcap) if fcf and mcap else None
        ps = f.get("priceToSalesTrailing12Months")
        ps_inv = (1.0 / ps) if ps and ps > 0 else None
        r["value"] = _mean_opt([
            _ramp(earn_yield, 0.0, 10, 0.08, 90),    # fwd P/E 25 -> 50, P/E 12.5 -> 90
            _ramp(fcf_yield, -0.01, 12, 0.07, 85),   # FCF yield 3% -> ~55
            _ramp(ps_inv, 0.02, 15, 0.50, 85),       # P/S 50 -> 15, P/S 2 -> 85
        ])
        r["growth"] = _mean_opt([
            _ramp(f.get("revenueGrowth"), -0.15, 15, 0.45, 90),   # 0% -> 33, 30% -> 71
            _ramp(f.get("earningsGrowth"), -0.20, 15, 0.60, 90),
        ])
        r["profitability"] = _mean_opt([
            _ramp(f.get("operatingMargins"), -0.05, 20, 0.40, 88),
            _ramp(f.get("profitMargins"), -0.05, 20, 0.35, 88),
            _ramp(f.get("returnOnEquity"), 0.0, 25, 0.40, 88),
        ])
        ocf = f.get("operatingCashflow")
        r["cashflow"] = _mean_opt([
            _ramp(fcf_yield, -0.01, 12, 0.07, 85),
            _ramp((ocf / mcap) if ocf and mcap else None, 0.0, 20, 0.10, 88),
        ])

        price_now = closes[-1] if closes else f.get("currentPrice")
        tgt = f.get("targetMeanPrice")
        analyst_upside = (tgt / price_now - 1) if tgt and price_now else None
        rec = f.get("recommendationMean")
        rec_score = ((5 - rec) / 4 * 100) if rec else None  # 1=strong buy -> 100, 5=sell -> 0
        r["analyst"] = _mean_opt([
            _ramp(analyst_upside, -0.25, 10, 0.35, 90),  # 0% upside -> ~43, +20% -> ~70
            rec_score,
        ])

        llm = llm_news.get(sym)
        if llm:
            news_raw = float(llm["s"])
            r["news"] = _ramp(news_raw, -2, 20, 2, 80)
        else:
            cur = con.execute(
                "SELECT COALESCE(SUM(sentiment),0) s, COUNT(*) c FROM news WHERE symbol=? AND published_at>=?",
                (sym, cutoff_news),
            ).fetchone()
            news_raw = float(cur["s"]) if cur["c"] else None
            r["news"] = _ramp(news_raw, -5, 25, 5, 75) if news_raw is not None else None

        raw[sym] = dict(r)
        raw[sym]["news"] = news_raw  # keep raw sentiment for tip generation
        for fac in factor_names:
            per_factor[fac][sym] = r[fac]

    # Absolute standalone scores: missing data -> neutral 50. No cross-sectional ranking.
    ranks = {fac: {sym: (v if v is not None else 50.0) for sym, v in vals.items()}
             for fac, vals in per_factor.items()}

    weights = {"momentum": 0.18, "value": 0.12, "growth": 0.14, "profitability": 0.10,
               "cashflow": 0.08, "analyst": 0.18, "news": 0.08, "risk": 0.12}

    composite_raw: dict[str, float] = {}
    for stock in universe:
        sym = stock["symbol"]
        composite_raw[sym] = sum(ranks[fac][sym] * w for fac, w in weights.items())

    # Blend absolute composite with cross-sectional rank so scores spread out
    # but extremes still require genuinely strong data.
    prev_scores: dict[str, float] = {}
    for r in con.execute(
        "SELECT symbol, score FROM scores WHERE date=(SELECT MAX(date) FROM scores WHERE date<?)", (as_of,)
    ).fetchall():
        prev_scores[r["symbol"]] = r["score"]

    FACTOR_HU = {"momentum": "momentum", "value": "értékeltség", "growth": "növekedés",
                 "profitability": "jövedelmezőség", "cashflow": "cash flow",
                 "analyst": "elemzői kép", "news": "hírfolyam", "risk": "kockázati profil"}

    scores: dict[str, dict] = {}
    ordered = sorted(composite_raw, key=lambda s: composite_raw[s], reverse=True)
    n = len(ordered)
    for pos, sym in enumerate(ordered):
        stock = next(s for s in universe if s["symbol"] == sym)
        # Standalone absolute score: each factor is measured against fixed
        # benchmarks, so a stock's score does not depend on the other stocks.
        # The x1.6 stretch around 50 is a fixed transform (8-factor averaging
        # compresses toward the middle); it adds resolution, not ranking.
        score = round(max(0, min(100, 50 + (composite_raw[sym] - 50) * 1.6)), 1)
        if score >= 75:
            tier = "strong_buy"
        elif score >= 63:
            tier = "buy"
        elif score > 48:
            tier = "hold"
        elif score > 38:
            tier = "sell"
        else:
            tier = "strong_sell"

        f = fundamentals[sym]
        closes = [r["close"] for r in series[sym] if r["close"]]
        price_now = closes[-1] if closes else f.get("currentPrice")
        fair_value, models = fair_value_ensemble(f, price_now, universe, fundamentals)
        upside = (fair_value / price_now - 1) if fair_value and price_now else None
        valuation_label = valuation_bucket(upside)
        fv_vals = list(models.values())
        fv_spread = ((max(fv_vals) - min(fv_vals)) / price_now) if len(fv_vals) > 1 and price_now else None
        fv_agreement = (None if fv_spread is None else
                        "magas modell-egyetértés" if fv_spread < 0.25 else
                        "közepes modell-egyetértés" if fv_spread < 0.6 else
                        "alacsony modell-egyetértés - óvatosan")

        sub = {
            "relative_value": ranks["value"][sym],
            "momentum": ranks["momentum"][sym],
            "cash_flow": ranks["cashflow"][sym],
            "profitability": ranks["profitability"][sym],
            "growth": ranks["growth"][sym],
        }
        health = round(sum(sub.values()) / len(sub) / 20.0, 1)  # 0..5
        health_label = ("Kiváló" if health >= 4.0 else "Jó" if health >= 3.2
                        else "Közepes" if health >= 2.4 else "Gyenge")

        protips, bull, bear = generate_tips(sym, ranks, raw[sym], f, upside)

        contrib = sorted(((fac, (ranks[fac][sym] - 50) * weights[fac]) for fac in factor_names),
                         key=lambda kv: kv[1], reverse=True)
        strengths = [FACTOR_HU[fac] for fac, c in contrib[:2] if c > 1]
        weaknesses = [FACTOR_HU[fac] for fac, c in contrib[-2:] if c < -1]
        driver_parts = []
        if strengths:
            driver_parts.append("Erősségek: " + ", ".join(strengths))
        if weaknesses:
            driver_parts.append("Gyengeségek: " + ", ".join(weaknesses))
        driver_text = (" · ".join(driver_parts) + ". A pontszám abszolút, fix mércékhez mért - nem a többi részvényhez viszonyít.") if driver_parts else ""

        prev = prev_scores.get(sym)
        score_change = round(score - prev, 1) if prev is not None else None

        recent_news = [
            dict(r) for r in con.execute(
                "SELECT title, publisher, published_at, url, sentiment FROM news"
                " WHERE symbol=? ORDER BY published_at DESC LIMIT 3", (sym,)
            ).fetchall()
        ]

        prev_close = closes[-2] if len(closes) >= 2 else None
        scores[sym] = {
            "symbol": sym,
            "name": stock["name"],
            "sector": stock["sector"],
            "score": score,
            "tier": tier,
            "tier_label": TIER_LABELS_HU[tier],
            "conviction": round(abs(score - 50) / 5, 1),  # 0-10 scale
            "health": health,
            "health_label": health_label,
            "health_components": sub,
            "factor_ranks": {k: ranks[k][sym] for k in factor_names},
            "fair_value": round(fair_value, 2) if fair_value else None,
            "fair_value_models": models,
            "fv_agreement": fv_agreement,
            "upside_pct": round(upside * 100, 1) if upside is not None else None,
            "valuation_label": valuation_label,
            "analyst_actions": analyst_actions.get(sym, []),
            "news_ai_note": (llm_news.get(sym) or {}).get("r"),
            "news_targets": (llm_news.get(sym) or {}).get("t") or [],
            "analyst": {
                "target_mean": f.get("targetMeanPrice"),
                "target_high": f.get("targetHighPrice"),
                "target_low": f.get("targetLowPrice"),
                "analysts": f.get("numberOfAnalystOpinions"),
                "recommendation": f.get("recommendationKey"),
            },
            "protips": protips,
            "bull": bull,
            "bear": bear,
            "driver_text": driver_text,
            "score_change": score_change,
            "news": recent_news,
            "last_close": price_now,
            "prev_close": prev_close,
        }
        con.execute(
            "INSERT OR REPLACE INTO scores (symbol, date, score, tier, conviction, health,"
            " fair_value, upside, valuation_label, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sym, as_of, score, tier, scores[sym]["conviction"], health,
             scores[sym]["fair_value"], scores[sym]["upside_pct"], valuation_label,
             json.dumps(scores[sym], ensure_ascii=False)),
        )
    con.commit()
    return {"as_of": as_of, "stocks": scores}


def _mean_opt(values: list[float | None]) -> float | None:
    xs = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return sum(xs) / len(xs) if xs else None


def fair_value_ensemble(f: dict, price: float | None, universe: list[dict], fundamentals: dict) -> tuple[float | None, dict]:
    if not price:
        return None, {}
    models: dict[str, float] = {}
    tgt = f.get("targetMeanPrice")
    if tgt:
        models["analyst_consensus"] = float(tgt)
    feps = f.get("forwardEps")
    if feps and feps > 0:
        pes = sorted(v for s in universe for v in [fundamentals[s["symbol"]].get("forwardPE")] if v and 0 < v < 120)
        if pes:
            med = pes[len(pes) // 2]
            models["peer_multiple"] = feps * med
    fcf = f.get("freeCashflow")
    mcap = f.get("marketCap")
    shares = f.get("sharesOutstanding")
    growth = f.get("revenueGrowth")
    if fcf and fcf > 0 and shares:
        g = max(0.02, min(0.06, (growth or 0.04) / 2.5))
        value = fcf * (1 + g) / (0.09 - g)
        models["dcf_lite"] = value / shares
    clamped = {k: max(price * 0.4, min(price * 2.5, v)) for k, v in models.items()}
    if not clamped:
        return None, {}
    # Equal-weight average of the applicable models (InvestingPro-style);
    # the fv_agreement indicator carries the model-disagreement warning.
    mean = sum(clamped.values()) / len(clamped)
    return mean, {k: round(v, 2) for k, v in clamped.items()}


def valuation_bucket(upside: float | None) -> str:
    if upside is None:
        return "n/a"
    if upside > 0.25:
        return "Kifejezetten alulértékelt"
    if upside > 0.10:
        return "Alulértékelt"
    if upside >= -0.10:
        return "Korrekt árazás"
    return "Túlértékelt"


def generate_tips(sym: str, ranks: dict, raw: dict, f: dict, upside: float | None):
    protips: list[str] = []
    bull: list[str] = []
    bear: list[str] = []

    def rank(fac):
        return ranks[fac][sym]

    if rank("momentum") >= 80:
        bull.append("Erős ártrend: a momentum a mezőny felső ötödében van.")
    elif rank("momentum") <= 20:
        bear.append("Gyenge ártrend: a momentum a mezőny alsó ötödében van.")
    if rank("value") >= 80:
        bull.append("Vonzó értékeltség az univerzumhoz képest (eredmény- és FCF-hozam alapján).")
    elif rank("value") <= 20:
        bear.append("Feszített értékeltség a mezőnyhöz képest.")
    if rank("growth") >= 80:
        bull.append("Kiemelkedő árbevétel- és eredménynövekedés.")
    elif rank("growth") <= 20:
        bear.append("Lassuló vagy negatív növekedés.")
    if rank("profitability") >= 80:
        bull.append("Magas marzsok és erős tőkearányos megtérülés.")
    elif rank("profitability") <= 20:
        bear.append("Gyenge jövedelmezőség a mezőnyhöz képest.")
    if rank("cashflow") >= 80:
        bull.append("Erős szabad cash flow termelés.")
    elif rank("cashflow") <= 20:
        bear.append("Gyenge cash flow generálás.")
    if upside is not None:
        if upside > 0.15:
            bull.append(f"A fair érték modellek {upside*100:.0f}% felértékelődési teret jeleznek.")
        elif upside < -0.10:
            bear.append(f"A fair érték modellek szerint az árfolyam {abs(upside)*100:.0f}%-kal a reális érték felett jár.")
    rec = f.get("recommendationKey") or ""
    if rec in ("strong_buy", "buy"):
        bull.append(f"Az elemzői konszenzus vételt jelez ({f.get('numberOfAnalystOpinions') or '?'} elemző).")
    elif rec in ("sell", "strong_sell", "underperform"):
        bear.append("Az elemzői konszenzus negatív.")
    if raw.get("news") is not None:
        if raw["news"] > 1:
            bull.append("A friss hírfolyam összképe pozitív.")
        elif raw["news"] < -1:
            bear.append("A friss hírfolyam összképe negatív.")

    protips = (bull[:3] + bear[:2])[:4]
    return protips, bull[:4], bear[:4]


# ------------------------------------------------------------ shadow engine

def last_close(con: sqlite3.Connection, symbol: str, on_or_before: str | None = None) -> tuple[str, float] | None:
    if on_or_before:
        row = con.execute(
            "SELECT date, close FROM prices_daily WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
            (symbol, on_or_before),
        ).fetchone()
    else:
        row = con.execute(
            "SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 1", (symbol,)
        ).fetchone()
    return (row["date"], row["close"]) if row and row["close"] else None


def prev_close(con: sqlite3.Connection, symbol: str, before: str) -> float | None:
    row = con.execute(
        "SELECT close FROM prices_daily WHERE symbol=? AND date<? ORDER BY date DESC LIMIT 1",
        (symbol, before),
    ).fetchone()
    return row["close"] if row else None


def _rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for i in range(-14, 0):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def harvest_signal(con: sqlite3.Connection, symbol: str) -> str | None:
    """Profit-harvest trigger (backtest round 2): RSI(14)>80 spike, or price
    3 std-devs above its 150-day mean. Returns Hungarian reason or None."""
    closes = [r["close"] for r in price_series(con, symbol, 220) if r["close"]]
    if len(closes) < 160:
        return None
    rsi = _rsi14(closes)
    if rsi is not None and rsi > 80:
        return f"RSI {rsi:.0f} > 80 (túlfűtött)"
    win = closes[-150:]
    mean = sum(win) / len(win)
    sd = (sum((x - mean) ** 2 for x in win) / len(win)) ** 0.5
    if sd > 0 and (closes[-1] - mean) / sd > 3:
        return "ár 3 szórással a 150 napos átlag felett"
    return None


def run_shadow(con: sqlite3.Connection, state: dict) -> dict:
    as_of = state["as_of"]
    stocks = state["stocks"]

    # 1. Close open lots that hit target/stop/max-hold/signal-flip.
    for lot in con.execute("SELECT * FROM shadow_lots WHERE status='open'").fetchall():
        sym = lot["symbol"]
        lc = last_close(con, sym)
        if not lc:
            continue
        cur_date, cur = lc
        direction = 1 if lot["side"] == "long" else -1
        ret = (cur / lot["entry_price"] - 1) * direction
        reason = None
        tier = stocks.get(sym, {}).get("tier", "hold")
        if lot["side"] == "short" and ret >= SHORT_TARGET:
            reason = "célár elérve"
        elif lot["side"] == "short" and ret <= SHORT_STOP:
            reason = "stop-loss"
        elif lot["side"] == "long" and ret > 0 and tier in ("sell", "strong_sell"):
            reason = "jelzés megfordult (profitban zárva)"
        elif lot["side"] == "short" and tier in ("buy", "strong_buy"):
            reason = "jelzés megfordult"
        if reason:
            pnl = round(lot["invested"] * ret, 2)
            con.execute(
                "UPDATE shadow_lots SET status='closed', exit_date=?, exit_price=?, exit_reason=?, pnl=?"
                " WHERE id=?",
                (cur_date, cur, reason, pnl, lot["id"]),
            )

    # 1b. Fill pending rebuy orders: 2% below sale price melting to any tick
    # below by day 10; never chase above the sale price.
    for r in con.execute("SELECT * FROM shadow_rebuys WHERE status='pending'").fetchall():
        lc = last_close(con, r["symbol"])
        if not lc:
            continue
        cur_date, cur = lc
        tdays = con.execute(
            "SELECT COUNT(*) c FROM prices_daily WHERE symbol=? AND date>? AND date<=?",
            (BENCHMARK, r["sale_date"], cur_date)).fetchone()["c"]
        threshold = r["sale_price"] * (1 - 0.02 * max(0.0, 1 - tdays / 10))
        if cur < r["sale_price"] and cur <= threshold:
            con.execute(
                "INSERT INTO shadow_lots (opened_date, symbol, side, entry_price, qty, invested)"
                " VALUES (?,?,?,?,?,?)",
                (cur_date, r["symbol"], "long", round(cur, 4), round(r["amount"] / cur, 6), r["amount"]))
            con.execute("UPDATE shadow_rebuys SET status='filled', filled_date=?, filled_price=? WHERE id=?",
                        (cur_date, cur, r["id"]))

    # 1c. Profit harvest: on a spike trigger sell HALF of each profitable long
    # lot and queue a rebuy order for the proceeds (sell-half variant, per Aron).
    long_syms = [r["symbol"] for r in con.execute(
        "SELECT DISTINCT symbol FROM shadow_lots WHERE status='open' AND side='long'").fetchall()]
    for sym in long_syms:
        if con.execute("SELECT 1 FROM shadow_rebuys WHERE symbol=? AND status='pending'", (sym,)).fetchone():
            continue
        sig = harvest_signal(con, sym)
        if not sig:
            continue
        lc = last_close(con, sym)
        if not lc:
            continue
        cur_date, cur = lc
        proceeds = 0.0
        for lot in con.execute(
                "SELECT * FROM shadow_lots WHERE status='open' AND side='long' AND symbol=?", (sym,)).fetchall():
            ret = cur / lot["entry_price"] - 1
            if ret <= 0:
                continue  # never harvest at a loss
            half_inv = round(lot["invested"] / 2, 2)
            half_qty = round(lot["qty"] / 2, 6)
            pnl = round(half_inv * ret, 2)
            con.execute("UPDATE shadow_lots SET invested=?, qty=? WHERE id=?",
                        (half_inv, half_qty, lot["id"]))
            con.execute(
                "INSERT INTO shadow_lots (opened_date, symbol, side, entry_price, qty, invested,"
                " status, exit_date, exit_price, exit_reason, pnl)"
                " VALUES (?,?,?,?,?,?,'closed',?,?,?,?)",
                (lot["opened_date"], sym, "long", lot["entry_price"], half_qty, half_inv,
                 cur_date, cur, f"profit-harvest fél pozíció ({sig})", pnl))
            proceeds += half_inv + pnl
        if proceeds:
            con.execute("INSERT INTO shadow_rebuys (symbol, sale_date, sale_price, amount) VALUES (?,?,?,?)",
                        (sym, cur_date, round(cur, 4), round(proceeds, 2)))
            print(f"Profit-harvest {sym}: fél pozíció eladva ({sig}), rebuy order {proceeds:.0f} USD")

    # 2. Open today's batch (once per trading day).
    existing = con.execute("SELECT 1 FROM shadow_batches WHERE date=?", (as_of,)).fetchone()
    if not existing:
        candidates = ([s for s in stocks.values() if s["tier"] in ("strong_buy", "buy") and s["last_close"]]
                      + [s for s in stocks.values() if s["tier"] == "strong_sell"
                         and s["score"] <= SHORT_MAX_SCORE and s["last_close"]])
        candidates.sort(key=lambda s: s["conviction"], reverse=True)
        picks = candidates[:DAILY_PICKS]
        for s in picks:
            side = "long" if s["tier"] in ("buy", "strong_buy") else "short"
            price = float(s["last_close"])
            qty = LOT_SIZE_USD / price
            con.execute(
                "INSERT INTO shadow_lots (opened_date, symbol, side, entry_price, qty, invested)"
                " VALUES (?,?,?,?,?,?)",
                (as_of, s["symbol"], side, round(price, 4), round(qty, 6), LOT_SIZE_USD),
            )
        con.execute(
            "INSERT INTO shadow_batches (date, picks) VALUES (?,?)",
            (as_of, json.dumps([
                {"symbol": s["symbol"], "side": "long" if s["tier"] in ("buy", "strong_buy") else "short",
                 "score": s["score"], "tier": s["tier"]}
                for s in picks
            ])),
        )
        spy = last_close(con, BENCHMARK)
        if spy:
            qty = (LOT_SIZE_USD * DAILY_PICKS) / spy[1]
            con.execute(
                "INSERT INTO benchmark_lots (opened_date, entry_price, qty, invested) VALUES (?,?,?,?)",
                (as_of, spy[1], round(qty, 6), LOT_SIZE_USD * DAILY_PICKS),
            )
        print(f"Shadow batch {as_of}: " + ", ".join(
            f"{s['symbol']}({'L' if s['tier'] in ('buy','strong_buy') else 'S'} {s['score']:.0f})" for s in picks))
    con.commit()

    # 3. Mark to market -> snapshot payload.
    positions = []
    unrealized = 0.0
    open_value = 0.0
    day_pnl = 0.0
    for lot in con.execute("SELECT * FROM shadow_lots WHERE status='open' ORDER BY opened_date DESC, id").fetchall():
        lc = last_close(con, lot["symbol"])
        if not lc:
            continue
        cur_date, cur = lc
        direction = 1 if lot["side"] == "long" else -1
        ret = (cur / lot["entry_price"] - 1) * direction
        pnl = lot["invested"] * ret
        value = lot["invested"] + pnl
        pc = prev_close(con, lot["symbol"], cur_date)
        d_pnl = lot["invested"] * ((cur / pc - 1) * direction) if pc and lot["opened_date"] < cur_date else (
            lot["invested"] * ret if lot["opened_date"] == cur_date else 0.0)
        unrealized += pnl
        open_value += value
        day_pnl += d_pnl
        srow = state["stocks"].get(lot["symbol"], {})
        positions.append({
            "id": lot["id"], "symbol": lot["symbol"], "side": lot["side"],
            "opened": lot["opened_date"], "entry": round(lot["entry_price"], 2),
            "qty": round(lot["qty"], 4), "invested": lot["invested"],
            "current": round(cur, 2), "value": round(value, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(ret * 100, 2),
            "day_pnl": round(d_pnl, 2),
            "tier": srow.get("tier"), "tier_label": srow.get("tier_label"),
        })
    closed = [dict(r) for r in con.execute(
        "SELECT opened_date, symbol, side, entry_price, exit_date, exit_price, exit_reason, invested, pnl"
        " FROM shadow_lots WHERE status='closed' ORDER BY exit_date DESC").fetchall()]
    realized = con.execute("SELECT COALESCE(SUM(pnl),0) p FROM shadow_lots WHERE status='closed'").fetchone()["p"]
    invested_open = con.execute("SELECT COALESCE(SUM(invested),0) i FROM shadow_lots WHERE status='open'").fetchone()["i"]
    invested_total = con.execute("SELECT COALESCE(SUM(invested),0) i FROM shadow_lots").fetchone()["i"]

    bench_value = 0.0
    bench_invested = 0.0
    spy_now = last_close(con, BENCHMARK)
    for lot in con.execute("SELECT * FROM benchmark_lots").fetchall():
        bench_invested += lot["invested"]
        if spy_now:
            bench_value += lot["qty"] * spy_now[1]
    batches = [
        {"date": r["date"], "picks": json.loads(r["picks"])}
        for r in con.execute("SELECT date, picks FROM shadow_batches ORDER BY date DESC LIMIT 15").fetchall()
    ]
    total_pnl = realized + unrealized
    shadow = {
        "v2": True,
        "as_of": as_of,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start_date": batches[-1]["date"] if batches else as_of,
        "rules": {
            "lot_usd": LOT_SIZE_USD, "daily_picks": DAILY_PICKS,
            "long_loss_realization": "soha",
            "short_target_pct": SHORT_TARGET * 100, "short_stop_pct": SHORT_STOP * 100,
        },
        "invested_total": round(invested_total, 2),
        "invested_open": round(invested_open, 2),
        "open_value": round(open_value, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / invested_total * 100, 2) if invested_total else 0.0,
        "day_pnl": round(day_pnl, 2),
        "positions": positions,
        "rebuy_orders": [dict(r) for r in con.execute(
            "SELECT symbol, sale_date, sale_price, amount FROM shadow_rebuys WHERE status='pending'").fetchall()],
        "closed": closed,
        "batches": batches,
        "benchmark": {
            "symbol": BENCHMARK,
            "invested": round(bench_invested, 2),
            "value": round(bench_value, 2),
            "pnl": round(bench_value - bench_invested, 2),
            "pnl_pct": round((bench_value / bench_invested - 1) * 100, 2) if bench_invested else 0.0,
        },
    }
    return shadow


# -------------------------------------------------------------- entrypoints

def write_snapshots(state: dict, shadow: dict) -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    daily = {
        "as_of": state["as_of"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe_count": len(state["stocks"]),
        "stocks": state["stocks"],
    }
    (SNAPSHOT_DIR / "daily_state.json").write_text(
        json.dumps(daily, ensure_ascii=False), encoding="utf-8")
    (SNAPSHOT_DIR / "shadow_state.json").write_text(
        json.dumps(shadow, ensure_ascii=False), encoding="utf-8")
    print(f"Snapshots written (as_of {state['as_of']}).")


def cmd_init() -> None:
    universe = load_universe()
    con = connect()
    init_schema(con)
    fetch_prices(con, [s["symbol"] for s in universe], full=True)
    fetch_fundamentals(con, universe)
    fetch_news(con, universe)
    con.close()
    print("Init done. Now run: python pipeline.py daily")


def cmd_daily() -> None:
    universe = load_universe()
    con = connect()
    init_schema(con)
    fetch_prices(con, [s["symbol"] for s in universe], full=False)
    fetch_fundamentals(con, universe)
    fetch_news(con, universe)
    fetch_analyst_actions(con, universe)
    env = load_env_file()
    llm = llm_news_scores(con, universe, env.get("OPENAI_API_KEY"),
                          env.get("OPENAI_MODEL") or "gpt-4o-mini")
    state = compute_scores(con, universe, llm)
    shadow = run_shadow(con, state)
    write_snapshots(state, shadow)
    con.close()
    print(f"Daily run complete. Total P&L: {shadow['total_pnl']:+.2f} USD"
          f" ({shadow['total_pnl_pct']:+.2f}%) vs SPY {shadow['benchmark']['pnl_pct']:+.2f}%")


def cmd_status() -> None:
    con = connect()
    init_schema(con)
    for table in ("prices_daily", "fundamentals", "news", "scores", "shadow_lots", "shadow_batches"):
        n = con.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        print(f"{table}: {n}")
    print("latest trading date:", latest_trading_date(con))
    con.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd == "init":
        cmd_init()
    elif cmd == "daily":
        cmd_daily()
    elif cmd == "status":
        cmd_status()
    else:
        print("usage: python pipeline.py [init|daily|status]")
