from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import random
import re
import sys
from statistics import fmean, pstdev
import xml.etree.ElementTree as ET
from urllib.parse import quote as url_quote, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).parent
PORT = 8000
CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "tozsde-ai-preview-cache" if os.environ.get("VERCEL") else ROOT / ".tmp" / "preview-cache"
LOGO_PATH = ROOT / "brand" / "tozsde-ai-logo-light-cropped.png"
LOGO_HERO_PATH = ROOT / "brand" / "tozsde-ai-logo-light.png"
FRONTEND_PATH = ROOT / "frontend_light.html"
LATEST_STATE_CACHE = "latest_state_v2"
CURRENT_STATE: dict | None = None
CURRENT_STATE_AT: datetime | None = None


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    keys = {"OPENAI_API_KEY", "ALPHAVANTAGE_API_KEY", "FMP_API_KEY"}
    values: dict[str, str] = {key: os.environ[key] for key in keys if os.environ.get(key)}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            clean_key = key.strip()
            if clean_key not in values:
                values[clean_key] = value.strip().strip('"').strip("'")
    return values


def load_portfolio() -> list[dict]:
    text = (ROOT / "portfolio.yml").read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*-\s+symbol:\s+", "\n" + text)[1:]
    stocks: list[dict] = []
    for block in blocks:
        lines = block.splitlines()
        symbol = lines[0].strip().strip('"').strip("'").upper()
        item = {"symbol": symbol, "name": symbol, "sector": "Ismeretlen", "exchange": "Ismeretlen"}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in item:
                item[key] = value
        stocks.append(item)
    return stocks


def cache_get(name: str, max_age_minutes: int) -> dict | list | None:
    path = CACHE_DIR / f"{name}.json"
    if not path.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    if age > timedelta(minutes=max_age_minutes):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cache_set(name: str, payload: dict | list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --- v2 snapshot (generated locally by pipeline.py, committed in snapshot/) ---

SNAPSHOT_DIR = ROOT / "snapshot"
TIER_TO_CATEGORY = {"strong_buy": "buy", "buy": "buy", "hold": "hold", "sell": "sell", "strong_sell": "sell"}


def _load_snapshot_file(filename: str) -> dict | None:
    path = SNAPSHOT_DIR / filename
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_v2_snapshot() -> dict | None:
    data = _load_snapshot_file("daily_state.json")
    return data if data and data.get("stocks") else None


def load_v2_shadow() -> dict | None:
    data = _load_snapshot_file("shadow_state.json")
    return data if data and data.get("v2") else None


def v2_decision_text(v2: dict) -> str:
    parts = [f"{v2.get('tier_label', '')} ({float(v2.get('score') or 0):.0f}/100 pont)."]
    health = v2.get("health")
    if health is not None:
        parts.append(f"Pénzügyi egészség: {health}/5 ({v2.get('health_label', '')}).")
    fv = v2.get("fair_value")
    up = v2.get("upside_pct")
    if fv is not None and up is not None:
        parts.append(f"Fair érték: {fv:.0f} USD ({up:+.0f}%), {v2.get('valuation_label', '')}.")
    return " ".join(parts)


def apply_v2_overlay(rows: list[dict], snapshot: dict) -> None:
    stocks = snapshot.get("stocks") or {}
    for row in rows:
        v2 = stocks.get(str(row.get("symbol") or "").upper())
        if not v2:
            continue
        row["score"] = float(v2.get("score") or row.get("score") or 50)
        row["conviction"] = float(v2.get("conviction") or abs(row["score"] - 50))
        cat = TIER_TO_CATEGORY.get(v2.get("tier"), row.get("category") or "hold")
        row["category"] = cat
        row["category_class"] = category_class(cat)
        row["tier"] = v2.get("tier")
        row["tier_label"] = v2.get("tier_label")
        row["health"] = v2.get("health")
        row["health_label"] = v2.get("health_label")
        row["health_components"] = v2.get("health_components")
        row["factor_ranks"] = v2.get("factor_ranks")
        row["fair_value"] = v2.get("fair_value")
        row["upside_pct"] = v2.get("upside_pct")
        row["valuation_label"] = v2.get("valuation_label")
        row["protips"] = v2.get("protips")
        row["bull_case"] = v2.get("bull")
        row["bear_case"] = v2.get("bear")
        row["fair_value_models"] = v2.get("fair_value_models")
        row["fv_agreement"] = v2.get("fv_agreement")
        row["analyst_actions"] = v2.get("analyst_actions")
        row["driver_text"] = v2.get("driver_text")
        row["score_change"] = v2.get("score_change")
        row["analyst_summary"] = v2.get("analyst")
        row["decision"] = v2_decision_text(v2)
        row["v2"] = True


def fetch_json(url: str, timeout: int = 8, headers: dict[str, str] | None = None) -> dict | list | None:
    try:
        request = Request(url, headers=headers or {"User-Agent": "TozsdeAI/0.1"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def fetch_json_status(url: str, timeout: int = 8, headers: dict[str, str] | None = None) -> tuple[dict | list | None, int | None, str | None]:
    try:
        request = Request(url, headers=headers or {"User-Agent": "TozsdeAI/0.1"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), response.status, None
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = None
        return payload, exc.code, str(exc)
    except URLError as exc:
        return None, None, str(exc.reason)
    except Exception as exc:
        return None, None, str(exc)


def certain_key_error(payload: dict | list | None, status: int | None) -> bool:
    if status in {401, 403}:
        return True
    text = json.dumps(payload, ensure_ascii=False).lower() if payload is not None else ""
    hard_markers = ["invalid api", "invalid key", "api key is invalid", "not authorized", "unauthorized", "forbidden"]
    return any(marker in text for marker in hard_markers)


def validate_sources(env: dict[str, str]) -> list[dict]:
    cached = cache_get("source_validation_v2", 180)
    if isinstance(cached, list):
        return cached

    issues: list[dict] = []
    required = [
        ("OPENAI_API_KEY", "OpenAI", "Magyar AI összefoglalók és napi riportok."),
        ("ALPHAVANTAGE_API_KEY", "Alpha Vantage", "Napi árfolyam-idősorok."),
        ("FMP_API_KEY", "FMP", "Célárak, elemzői adatok és strukturált hírek."),
    ]
    for key, source, role in required:
        if not env.get(key):
            issues.append(
                {
                    "severity": "critical",
                    "source": source,
                    "title": f"{source} kulcs hiányzik",
                    "detail": f"A(z) {key} nincs beállítva. Érintett funkció: {role}",
                }
            )

    if env.get("OPENAI_API_KEY"):
        payload, status, _error = fetch_json_status(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {env['OPENAI_API_KEY']}", "User-Agent": "TozsdeAI/0.1"},
        )
        if certain_key_error(payload, status):
            issues.append(
                {
                    "severity": "critical",
                    "source": "OpenAI",
                    "title": "OpenAI kulcshiba",
                    "detail": "Az OpenAI végpont kifejezetten jogosultsági vagy érvénytelen kulcs hibát adott vissza.",
                }
            )

    if env.get("ALPHAVANTAGE_API_KEY"):
        params = urlencode({"function": "GLOBAL_QUOTE", "symbol": "MSFT", "apikey": env["ALPHAVANTAGE_API_KEY"]})
        payload, status, _error = fetch_json_status(f"https://www.alphavantage.co/query?{params}")
        if certain_key_error(payload, status) or (isinstance(payload, dict) and "Error Message" in payload):
            issues.append(
                {
                    "severity": "critical",
                    "source": "Alpha Vantage",
                    "title": "Alpha Vantage kulcshiba",
                    "detail": "Az Alpha Vantage válasza biztos kulcs- vagy jogosultsági hibát jelzett.",
                }
            )

    if env.get("FMP_API_KEY"):
        params = urlencode({"symbol": "MSFT", "apikey": env["FMP_API_KEY"]})
        payload, status, _error = fetch_json_status(f"https://financialmodelingprep.com/stable/quote-short?{params}")
        if certain_key_error(payload, status):
            issues.append(
                {
                    "severity": "critical",
                    "source": "FMP",
                    "title": "FMP kulcshiba",
                    "detail": "Az FMP végpont biztos kulcs- vagy jogosultsági hibát adott vissza.",
                }
            )

    cache_set("source_validation_v2", issues)
    return issues


def live_quotes(symbols: list[str], api_key: str | None, issues: list[dict]) -> dict[str, dict]:
    if not api_key:
        return {}
    cached = cache_get("fmp_batch_quotes", 30)
    if isinstance(cached, dict):
        return cached

    quotes: dict[str, dict] = {}
    for idx in range(0, len(symbols), 25):
        chunk = symbols[idx : idx + 25]
        params = urlencode({"symbols": ",".join(chunk), "apikey": api_key})
        payload = fetch_json(f"https://financialmodelingprep.com/stable/batch-quote-short?{params}")
        if isinstance(payload, list):
            for item in payload:
                symbol = str(item.get("symbol") or "").upper()
                if symbol:
                    quotes[symbol] = item
    if quotes:
        cache_set("fmp_batch_quotes", quotes)
        return quotes
    return {}


def live_full_quotes(symbols: list[str], api_key: str | None) -> dict[str, dict]:
    """Fetch full FMP quotes including P/E, EPS, market cap, 52-week range, next earnings date.

    Cached for 6 hours; this data shifts slowly intraday but earnings dates are stable.
    Falls back to the legacy /api/v3/quote/{symbols} endpoint if /stable/quote is restricted.
    """
    if not api_key:
        return {}
    cached = cache_get("fmp_batch_full_quotes_v1", 360)
    if isinstance(cached, dict):
        return cached

    quotes: dict[str, dict] = {}
    for idx in range(0, len(symbols), 25):
        chunk = symbols[idx : idx + 25]
        symbols_str = ",".join(chunk)
        payload = fetch_json(
            f"https://financialmodelingprep.com/api/v3/quote/{symbols_str}?apikey={api_key}",
            timeout=12,
        )
        if not isinstance(payload, list) or not payload:
            params = urlencode({"symbols": symbols_str, "apikey": api_key})
            payload = fetch_json(
                f"https://financialmodelingprep.com/stable/quote?{params}",
                timeout=12,
            )
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper()
                if symbol:
                    quotes[symbol] = item
    if quotes:
        cache_set("fmp_batch_full_quotes_v1", quotes)
    return quotes


def safe_cache_name(prefix: str, symbol: str) -> str:
    clean = re.sub(r"[^A-Z0-9_-]+", "_", symbol.upper())
    return f"{prefix}_{clean}"


def normalize_history_rows(payload: list | dict | None) -> list[dict]:
    rows = payload if isinstance(payload, list) else payload.get("historical", []) if isinstance(payload, dict) else []
    normalized: list[dict] = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("date"):
            continue
        try:
            normalized.append(
                {
                    "date": str(item["date"])[:10],
                    "open": round(float(item.get("open") or item.get("close") or 0), 2),
                    "high": round(float(item.get("high") or item.get("close") or 0), 2),
                    "low": round(float(item.get("low") or item.get("close") or 0), 2),
                    "close": round(float(item.get("close") or 0), 2),
                    "volume": int(float(item.get("volume") or 0)),
                    "source": "fmp_historical_eod",
                }
            )
        except (TypeError, ValueError):
            continue
    normalized = [row for row in normalized if row["close"] > 0]
    normalized.sort(key=lambda row: row["date"])
    deduped: dict[str, dict] = {row["date"]: row for row in normalized}
    return [deduped[key] for key in sorted(deduped)]


def fetch_fmp_history(symbol: str, api_key: str) -> list[dict]:
    cached = cache_get(safe_cache_name("fmp_history", symbol), 720)
    if isinstance(cached, list) and len(cached) >= 60:
        return cached
    start = (date.today() - timedelta(days=460)).isoformat()
    params = urlencode({"symbol": symbol, "from": start, "apikey": api_key})
    payload, status, _error = fetch_json_status(f"https://financialmodelingprep.com/stable/historical-price-eod/full?{params}", timeout=20)
    if status == 429:
        cache_set("fmp_history_rate_limited", {"at": datetime.now().isoformat(), "symbol": symbol})
        return []
    rows = normalize_history_rows(payload)
    if len(rows) >= 60:
        cache_set(safe_cache_name("fmp_history", symbol), rows[-320:])
        return rows[-320:]
    return []


def yahoo_symbol(symbol: str) -> str:
    return symbol.upper().replace(".", "-")


def normalize_yahoo_chart(payload: dict | list | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not isinstance(result, dict):
        return []
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    rows: list[dict] = []
    for idx, ts in enumerate(timestamps):
        try:
            close = closes[idx]
            if close is None:
                continue
            open_value = opens[idx] if idx < len(opens) and opens[idx] is not None else close
            high_value = highs[idx] if idx < len(highs) and highs[idx] is not None else close
            low_value = lows[idx] if idx < len(lows) and lows[idx] is not None else close
            volume_value = volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 0
            rows.append(
                {
                    "date": datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat(),
                    "open": round(float(open_value), 2),
                    "high": round(float(high_value), 2),
                    "low": round(float(low_value), 2),
                    "close": round(float(close), 2),
                    "volume": int(float(volume_value)),
                    "source": "yahoo_chart_daily",
                }
            )
        except (IndexError, TypeError, ValueError, OSError):
            continue
    deduped: dict[str, dict] = {row["date"]: row for row in rows if row["close"] > 0}
    return [deduped[key] for key in sorted(deduped)]


def fetch_yahoo_history(symbol: str) -> list[dict]:
    cached = cache_get(safe_cache_name("yahoo_history", symbol), 720)
    if isinstance(cached, list) and len(cached) >= 60:
        return cached
    params = urlencode({"range": "1y", "interval": "1d", "includePrePost": "false"})
    encoded_symbol = url_quote(yahoo_symbol(symbol), safe="")
    payload = fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?{params}", timeout=20)
    rows = normalize_yahoo_chart(payload)
    if len(rows) >= 60:
        cache_set(safe_cache_name("yahoo_history", symbol), rows[-320:])
        return rows[-320:]
    return []


def fetch_yahoo_tape_quote(symbol: str, name: str, kind: str = "index") -> dict | None:
    cached = cache_get(safe_cache_name("yahoo_tape", symbol), 30)
    if isinstance(cached, dict):
        return cached
    params = urlencode({"range": "5d", "interval": "1d", "includePrePost": "false"})
    encoded_symbol = url_quote(yahoo_symbol(symbol), safe="")
    payload = fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?{params}", timeout=10)
    rows = normalize_yahoo_chart(payload)
    if len(rows) < 2:
        return None
    latest = rows[-1]
    previous = rows[-2]
    price = float(latest["close"])
    prev_price = float(previous["close"])
    change = price - prev_price
    change_pct = (change / prev_price * 100) if prev_price else 0.0
    item = {
        "symbol": symbol,
        "name": name,
        "kind": kind,
        "latest_price": price,
        "latest_change": change,
        "latest_change_pct": change_pct,
        "date": latest.get("date"),
        "source": "Yahoo Finance",
    }
    cache_set(safe_cache_name("yahoo_tape", symbol), item)
    return item


def build_market_tape(rows: list[dict]) -> list[dict]:
    tape: list[dict] = []
    for symbol, name in [
        ("^GSPC", "S&P 500"),
        ("^IXIC", "Nasdaq"),
        ("^DJI", "Dow Jones"),
        ("^RUT", "Russell 2000"),
    ]:
        item = fetch_yahoo_tape_quote(symbol, name, "index")
        if item:
            tape.append(item)

    rows_by_symbol = {row.get("symbol"): row for row in rows}
    for symbol in ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA"]:
        row = rows_by_symbol.get(symbol)
        if not row:
            continue
        tape.append(
            {
                "symbol": symbol,
                "name": row.get("name") or symbol,
                "kind": "stock",
                "latest_price": row.get("latest_price"),
                "latest_change": row.get("latest_change"),
                "latest_change_pct": row.get("latest_change_pct"),
                "date": row.get("prices", [{}])[-1].get("date") if row.get("prices") else None,
                "source": row.get("price_source"),
            }
        )
    return tape


def live_price_history(symbols: list[str], api_key: str | None, issues: list[dict]) -> dict[str, list[dict]]:
    histories: dict[str, list[dict]] = {}
    missing: list[str] = []
    for symbol in symbols:
        cached = cache_get(safe_cache_name("yahoo_history", symbol), 720)
        if isinstance(cached, list) and len(cached) >= 60:
            histories[symbol] = cached
        else:
            missing.append(symbol)

    if missing:
        attempted_yahoo = missing[:]
        with ThreadPoolExecutor(max_workers=8) as pool:
            future_map = {pool.submit(fetch_yahoo_history, symbol): symbol for symbol in attempted_yahoo}
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    rows = future.result()
                except Exception:
                    rows = []
                if rows:
                    histories[symbol] = rows

    missing = [symbol for symbol in symbols if symbol not in histories]
    if not missing:
        return histories

    if not api_key:
        issues.append(
            {
                "severity": "warning",
                "source": "Yahoo Finance",
                "title": "Történeti árfolyam részlegesen elérhető",
                "detail": f"A Yahoo Finance kulcs nélkül {len(histories)} tickerhez adott napi történeti idősorokat, {len(missing)} ticker fallback idősoron marad.",
            }
        )
        return histories

    for symbol in missing[:]:
        cached = cache_get(safe_cache_name("fmp_history", symbol), 720)
        if isinstance(cached, list) and len(cached) >= 60:
            histories[symbol] = cached

    missing = [symbol for symbol in symbols if symbol not in histories]
    if not missing:
        return histories

    rate_limited = cache_get("fmp_history_rate_limited", 65)
    if isinstance(rate_limited, dict):
        if missing:
            issues.append(
                {
                    "severity": "warning",
                    "source": "FMP",
                    "title": "Történeti árfolyam-limit aktív",
                    "detail": f"Yahoo Finance és cache alapján {len(histories)} ticker valós idősorból megy. Az FMP 429 limitet adott, ezért {len(missing)} ticker a limit lejártáig fallback idősoron marad.",
                }
            )
        return histories
    if not missing:
        return histories

    failures = 0
    attempted = missing[:24]
    with ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {pool.submit(fetch_fmp_history, symbol, api_key): symbol for symbol in attempted}
        for future in as_completed(future_map):
            symbol = future_map[future]
            try:
                rows = future.result()
            except Exception:
                rows = []
            if rows:
                histories[symbol] = rows
            else:
                failures += 1
    remaining = len(symbols) - len(histories)
    if remaining:
        issues.append(
            {
                "severity": "warning",
                "source": "FMP",
                "title": "Történeti árfolyam részlegesen frissült",
                "detail": f"{len(histories)} ticker valós napi idősorból működik, {remaining} ticker még fallback idősoron van. A rendszer cache-eli a sikeres lekéréseket, és későbbi frissítésekkel folytatja.",
            }
        )
    if failures and failures == len(attempted) and not histories:
        issues.append(
            {
                "severity": "warning",
                "source": "FMP",
                "title": "Történeti árfolyam nem frissült",
                "detail": "Az FMP történeti napi árfolyam végpontból nem sikerült friss adatot lekérni; az érintett tickereknél fallback idősor jelenhet meg.",
            }
        )
    return histories


def live_news(symbols: list[str], api_key: str | None, issues: list[dict]) -> dict[str, list[dict]]:
    news_by_symbol: dict[str, list[dict]] = {symbol: [] for symbol in symbols}
    if api_key:
        cached = cache_get("fmp_stock_news_v2", 90)
        if isinstance(cached, dict):
            for symbol in symbols:
                news_by_symbol[symbol] = list(cached.get(symbol, []))
        else:
            # Official FMP stable docs support /news/stocksymbols=AAPL. Batches keep calls low.
            for idx in range(0, len(symbols), 20):
                chunk = symbols[idx : idx + 20]
                params = urlencode({"symbols": ",".join(chunk), "limit": 60, "apikey": api_key})
                payload = fetch_json(f"https://financialmodelingprep.com/stable/news/stock?{params}")
                if not isinstance(payload, list):
                    continue
                for item in payload:
                    raw = str(item.get("symbol") or item.get("symbols") or "").upper()
                    related = [s for s in chunk if s in raw.split(",") or s == raw]
                    if not related and len(chunk) == 1:
                        related = chunk
                    for symbol in related:
                        news_by_symbol.setdefault(symbol, []).append(
                            {
                                "title": item.get("title") or item.get("headline") or "Cím nélküli hír",
                                "site": item.get("site") or item.get("publisher") or "FMP",
                                "published_at": item.get("publishedDate") or item.get("date"),
                                "url": item.get("url"),
                                "text": item.get("text") or item.get("summary") or "",
                            }
                        )
            if any(news_by_symbol.values()):
                cache_set("fmp_stock_news_v2", news_by_symbol)

    missing = [symbol for symbol in symbols if len(news_by_symbol.get(symbol, [])) < 2]
    yahoo_news = live_yahoo_news(missing)
    for symbol, rows in yahoo_news.items():
        news_by_symbol.setdefault(symbol, []).extend(rows)
    return news_by_symbol


def live_yahoo_news(symbols: list[str]) -> dict[str, list[dict]]:
    news_by_symbol: dict[str, list[dict]] = {}
    if not symbols:
        return news_by_symbol

    def fetch_symbol(symbol: str) -> tuple[str, list[dict]]:
        cached = cache_get(safe_cache_name("yahoo_rss_news_v1", symbol), 180)
        if isinstance(cached, list):
            return symbol, cached
        encoded = url_quote(symbol.replace(".", "-"))
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={encoded}&region=US&lang=en-US"
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=5) as response:
                xml_text = response.read().decode("utf-8", errors="ignore")
        except Exception:
            return symbol, []
        rows: list[dict] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return symbol, []
        for item in root.findall("./channel/item")[:8]:
            title = html.unescape((item.findtext("title") or "").strip())
            description = html.unescape((item.findtext("description") or "").strip())
            description = re.sub(r"<[^>]+>", " ", description)
            description = re.sub(r"\s+", " ", description).strip()
            link = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or "").strip()
            source_node = item.find("source")
            source = (source_node.text or "").strip() if source_node is not None and source_node.text else "Yahoo Finance"
            if not title:
                continue
            rows.append(
                {
                    "title": title,
                    "site": source or "Yahoo Finance",
                    "published_at": published,
                    "url": link,
                    "text": description,
                    "source": "Yahoo Finance RSS",
                }
            )
        if rows:
            cache_set(safe_cache_name("yahoo_rss_news_v1", symbol), rows)
        return symbol, rows

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(fetch_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, rows = future.result()
            news_by_symbol[symbol] = rows
    return news_by_symbol


def live_macro_news(api_key: str | None) -> list[dict]:
    if not api_key:
        return []
    cached = cache_get("fmp_general_news", 90)
    if isinstance(cached, list):
        return cached
    params = urlencode({"page": 0, "limit": 8, "apikey": api_key})
    payload = fetch_json(f"https://financialmodelingprep.com/stable/news/general-latest?{params}")
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload[:14]:
        site = item.get("site") or item.get("publisher") or "FMP"
        if "youtube.com" in str(site).lower():
            continue
        rows.append(
            {
                "title": item.get("title") or item.get("headline") or "Cím nélküli piaci hír",
                "title_hu": macro_title_hu(item.get("title") or item.get("headline") or ""),
                "site": site,
                "published_at": item.get("publishedDate") or item.get("date"),
                "url": item.get("url"),
                "text": item.get("text") or item.get("summary") or "",
                "interpretation": macro_summary_hu(item.get("title") or item.get("headline") or "", item.get("text") or item.get("summary") or ""),
            }
        )
    if rows:
        cache_set("fmp_general_news", rows)
    return rows


def macro_title_hu(title: str) -> str:
    lower = str(title or "").lower()
    if has_any_news_keyword(lower, ["fed", "rates", "yield", "inflation", "cpi", "jobs", "payroll", "openings"]):
        return "Kamat- és inflációs hír mozgatja a piaci hangulatot"
    if has_any_news_keyword(lower, ["oil", "opec", "crude", "energy"]):
        return "Energiaár-hír hat a ciklikus és energia részvényekre"
    if has_any_news_keyword(lower, ["ai", "artificial intelligence", "chip", "semiconductor", "data center"]):
        return "AI- és chipkeresleti hír került a fókuszba"
    if has_any_news_keyword(lower, ["tariff", "trade", "china", "export"]):
        return "Kereskedelmi vagy geopolitikai kockázat jelent meg"
    if has_any_news_keyword(lower, ["earnings", "results", "guidance"]):
        return "Eredményszezonhoz kapcsolódó piaci hír"
    return "Friss piaci hír a befektetői hangulat szempontjából"


def macro_summary_hu(title: str, text: str) -> str:
    combined = f"{title} {text}".lower()
    if has_any_news_keyword(combined, ["fed", "rates", "yield", "inflation", "cpi", "jobs", "payroll", "openings"]):
        return "A hír a diszkontrátán és a kockázati étvágyon keresztül hathat: magasabb hozamkörnyezetben a növekedési részvények értékeltsége érzékenyebb."
    if has_any_news_keyword(combined, ["oil", "opec", "crude", "energy"]):
        return "Az energiaárak változása közvetlenül érinti az energia- és szállítmányozási cégek cash-flow kilátását, közvetve pedig az inflációs képet."
    if has_any_news_keyword(combined, ["ai", "artificial intelligence", "chip", "semiconductor", "data center"]):
        return "Az AI-infrastruktúra hírei a chipgyártók, adatközpont-szállítók és felhős cégek növekedési várakozásait mozgathatják."
    if has_any_news_keyword(combined, ["tariff", "trade", "china", "export"]):
        return "Kereskedelmi vagy geopolitikai hírnél a margin, ellátási lánc és végkereslet sérülékenysége a kulcskérdés."
    return "A hír piaci kontextust ad; az értéke abban van, hogy segít értelmezni a napi kockázati étvágyat és szektormozgásokat."


def live_calendar_events(symbols: list[str], api_key: str | None) -> dict[str, dict[str, list[dict]]]:
    events = {symbol: {"earnings": [], "dividends": []} for symbol in symbols}
    if not api_key:
        return events
    cached = cache_get("fmp_calendar_events_v1", 360)
    if isinstance(cached, dict):
        return {symbol: cached.get(symbol, {"earnings": [], "dividends": []}) for symbol in symbols}

    start = date.today()
    end = start + timedelta(days=120)
    endpoints = [
        ("earnings", "https://financialmodelingprep.com/stable/earnings-calendar"),
        ("dividends", "https://financialmodelingprep.com/stable/dividends-calendar"),
    ]
    symbol_set = set(symbols)
    for event_type, base_url in endpoints:
        params = urlencode({"from": start.isoformat(), "to": end.isoformat(), "apikey": api_key})
        payload = fetch_json(f"{base_url}?{params}", timeout=16)
        if not isinstance(payload, list):
            continue
        for item in payload:
            symbol = str(item.get("symbol") or "").upper()
            if symbol not in symbol_set:
                continue
            row = {
                "type": event_type,
                "symbol": symbol,
                "date": item.get("date") or item.get("paymentDate") or item.get("recordDate"),
                "title": "Következő eredményjelentés" if event_type == "earnings" else "Következő osztalékesemény",
                "eps_estimated": item.get("epsEstimated") or item.get("epsEstimatedAvg"),
                "revenue_estimated": item.get("revenueEstimated") or item.get("revenueEstimatedAvg"),
                "dividend": item.get("dividend") or item.get("adjDividend"),
                "payment_date": item.get("paymentDate"),
                "record_date": item.get("recordDate"),
                "source": "FMP calendar",
            }
            events[symbol][event_type].append(row)

    for symbol in symbols:
        for key in ("earnings", "dividends"):
            events[symbol][key] = sorted(
                [item for item in events[symbol][key] if item.get("date")],
                key=lambda item: str(item.get("date")),
            )[:3]
    cache_set("fmp_calendar_events_v1", events)
    return events


def normalize_analyst_target(symbol: str, payload: dict | list | None) -> dict:
    rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    item = next((row for row in rows if isinstance(row, dict)), {})
    def pick(*keys: str) -> float | None:
        for key in keys:
            value = item.get(key)
            if value in (None, ""):
                continue
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                continue
        return None
    def pick_int(*keys: str) -> int | None:
        value = pick(*keys)
        return int(value) if value is not None else None
    return {
        "symbol": symbol,
        "target_consensus": pick("targetConsensus", "targetConsensusEstimate", "consensus", "targetPrice", "priceTarget"),
        "target_high": pick("targetHigh", "high", "priceTargetHigh"),
        "target_low": pick("targetLow", "low", "priceTargetLow"),
        "target_median": pick("targetMedian", "median", "priceTargetMedian"),
        "analyst_count": pick_int("numberOfAnalysts", "analystCount", "analysts", "numberAnalystEstimated"),
        "source": "FMP price target consensus",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def fetch_analyst_target(symbol: str, api_key: str | None) -> dict:
    cached = cache_get(safe_cache_name("analyst_target_v2", symbol), 720)
    if isinstance(cached, dict):
        return cached
    if not api_key:
        return {
            "symbol": symbol,
            "target_consensus": None,
            "target_high": None,
            "target_low": None,
            "target_median": None,
            "analyst_count": None,
            "source": "FMP célár kulcs nélkül nem elérhető",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    params = urlencode({"symbol": symbol, "apikey": api_key})
    payload = fetch_json(f"https://financialmodelingprep.com/stable/price-target-consensus?{params}", timeout=12)
    target = normalize_analyst_target(symbol, payload)
    if target["target_consensus"] is None:
        payload = fetch_json(f"https://financialmodelingprep.com/api/v4/price-target-consensus?{params}", timeout=12)
        target = normalize_analyst_target(symbol, payload)
    cache_set(safe_cache_name("analyst_target_v2", symbol), target)
    return target


def fetch_analyst_targets_for_rows(rows: list[dict], env: dict[str, str]) -> dict[str, dict]:
    api_key = env.get("FMP_API_KEY")
    if not api_key:
        return {}
    symbols = [row.get("symbol") for row in rows if row.get("symbol")]
    targets: dict[str, dict] = {}
    fetch_candidates = symbols[:45]
    missing = [symbol for symbol in fetch_candidates if not isinstance(cache_get(safe_cache_name("analyst_target_v2", symbol), 720), dict)]
    if missing:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_analyst_target, symbol, api_key): symbol for symbol in missing}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    targets[symbol] = future.result()
                except Exception:
                    continue
    for symbol in symbols:
        cached = cached_analyst_target(symbol)
        if cached:
            targets[symbol] = cached
    return targets


def cached_analyst_target(symbol: str) -> dict | None:
    cached = cache_get(safe_cache_name("analyst_target_v2", symbol), 720)
    return cached if isinstance(cached, dict) else None


def investment_risk_score(row: dict, target_upside: float | None) -> int:
    risk_component = float((row.get("components") or {}).get("risk") or 50)
    data_quality = float(row.get("data_quality") or 0)
    daily_move = abs(float(row.get("latest_change_pct") or 0))
    target_swing = abs(float(target_upside or 0))
    score = 100 - risk_component
    if data_quality < 75:
        score += (75 - data_quality) * 0.55
    if daily_move >= 4:
        score += min(18, daily_move * 1.8)
    if target_swing >= 25:
        score += min(14, (target_swing - 25) * 0.7)
    return int(round(max(1, min(100, score))))


def investment_risk_level(row: dict, target_upside: float | None) -> str:
    score = investment_risk_score(row, target_upside)
    if score >= 66:
        return "magas"
    if score >= 36:
        return "közepes"
    return "alacsony"


def build_investment_ideas(rows: list[dict], env: dict[str, str]) -> list[dict]:
    actionable = sorted(rows, key=action_rank, reverse=True)
    analyst_targets = fetch_analyst_targets_for_rows(actionable, env)
    ideas = []
    for row in actionable:
        price = float(row.get("latest_price") or 0)
        if price <= 0:
            continue
        target = analyst_targets.get(row["symbol"]) or cached_analyst_target(row["symbol"])

        consensus = target.get("target_consensus") if isinstance(target, dict) else None
        analyst_high = target.get("target_high") if isinstance(target, dict) else None
        analyst_low = target.get("target_low") if isinstance(target, dict) else None
        analyst_median = target.get("target_median") if isinstance(target, dict) else None
        score = float(row.get("score") or 50)
        valuation = float((row.get("components") or {}).get("valuation") or 50)
        momentum = float((row.get("components") or {}).get("momentum") or 50)
        risk_component = float((row.get("components") or {}).get("risk") or 50)
        fundamentals = float((row.get("components") or {}).get("fundamentals") or 50)
        long_term_quality = fundamentals * 0.38 + valuation * 0.28 + risk_component * 0.22 + momentum * 0.12
        # Target a 1-2 year horizon with patient long-only investor in mind.
        # Score 60 -> ~18% upside; Score 70 -> ~32%; Score 80 -> ~46%.
        # Quality is a secondary multiplier; risk only penalizes when truly poor.
        score_upside = (score - 50) * 0.018
        quality_upside = (long_term_quality - 50) * 0.0065
        risk_penalty = max(0, 40 - risk_component) * 0.003
        model_upside = score_upside + quality_upside - risk_penalty
        model_upside = max(-0.40, min(0.90, model_upside))
        ai_target = price * (1 + model_upside)
        if consensus:
            cons_target = float(consensus)
            # If our model is more optimistic than consensus (typical for patient long-term view),
            # keep most of our view; only blend toward consensus when consensus is more optimistic.
            if ai_target >= cons_target:
                fair_target = cons_target * 0.20 + ai_target * 0.80
            else:
                fair_target = cons_target * 0.60 + ai_target * 0.40
            target_source = "Tőzsde AI 1-2 éves célár elemzői kontrollal"
        else:
            fair_target = ai_target
            target_source = "Tőzsde AI 1-2 éves célár"

        upside_pct = ((fair_target / price) - 1) * 100 if price else None
        risk_score = investment_risk_score(row, upside_pct)
        risk_level = investment_risk_level(row, upside_pct)
        daily_move = abs(float(row.get("latest_change_pct") or 0))
        cat = row.get("category") or "hold"
        is_short_signal = "sell" in cat or (upside_pct is not None and upside_pct < -5)

        if is_short_signal:
            # Short trade structure: enter near current (or small bounce), target = fair_target (below), stop above.
            bounce = 0.012 if risk_level == "alacsony" else 0.02 if risk_level == "közepes" else 0.03
            entry_high = price * (1 + bounce)
            entry_low = price * (1 - 0.005)
            entry_price = price
            stop_buffer = 0.06 if risk_level == "alacsony" else 0.08 if risk_level == "közepes" else 0.11
            review_down = price * (1 + stop_buffer)  # reused field: for shorts, this is the STOP (above current)
        else:
            entry_discount = 0.015
            if risk_level == "közepes":
                entry_discount = 0.035
            elif risk_level == "magas":
                entry_discount = 0.065
            if daily_move >= 5:
                entry_discount += 0.02
            entry_low = price * (1 - entry_discount)
            entry_high = price * (1 - max(0.006, entry_discount * 0.35))
            entry_price = entry_high
            review_down = price * (1 - (0.055 if risk_level == "alacsony" else 0.085 if risk_level == "közepes" else 0.12))

        # Timing score: based on absolute distance from 52-week high.
        # Calibrated for mega-cap behaviour — 10% off is already meaningful, 20%+ is generational.
        fd = row.get("fundamentals_data") or {}
        year_range_pos = fd.get("year_range_position")
        year_high = fd.get("year_high")
        year_low = fd.get("year_low")
        ath_distance_pct = None
        if year_high and price:
            ath_distance_pct = round((price / float(year_high) - 1) * 100, 2)

        timing_score = None
        timing_label = "n/a"
        timing_flag = False
        if ath_distance_pct is not None:
            abs_dist = -float(ath_distance_pct)  # positive number, distance below 52w high
            if abs_dist <= 0:
                timing_score = 10
                timing_label = "Kedvezőtlen"
            elif abs_dist <= 3:
                timing_score = 15 + (abs_dist / 3.0) * 20
                timing_label = "Kedvezőtlen"
            elif abs_dist <= 7:
                timing_score = 35 + ((abs_dist - 3.0) / 4.0) * 20
                timing_label = "Semleges"
            elif abs_dist <= 15:
                timing_score = 55 + ((abs_dist - 7.0) / 8.0) * 18
                timing_label = "Elfogadható"
            elif abs_dist <= 25:
                timing_score = 73 + ((abs_dist - 15.0) / 10.0) * 17
                timing_label = "Kedvező"
            else:
                # Deep drawdown — still attractive for mean-reversion but flag the risk
                timing_score = max(65, 90 - (abs_dist - 25.0) * 0.5)
                timing_label = "Kedvező (figyelem)"
                timing_flag = True
            timing_score = round(max(5, min(100, timing_score)), 1)

        if upside_pct is not None and upside_pct < -5:
            stance = "Célár alapján óvatos"
        elif "buy" in cat:
            stance = "1-2 éves vételi ötlet"
        elif "sell" in cat:
            stance = "Gyenge hosszabb távú jelzés"
        else:
            stance = "Figyelőlista"

        warnings = []
        if risk_level == "magas":
            warnings.append("Magas kockázat: nagyobb ármozgás, gyengébb kockázati komponens vagy alacsonyabb adatbizalom.")
        if upside_pct is not None and upside_pct < -5:
            warnings.append("A célár a jelenlegi ár alatt van, ezért beszálló csak jelentős visszaesés után értelmezhető.")
        if not consensus:
            warnings.append("Nincs friss elemzői konszenzus célár; ilyenkor a Tőzsde AI célár látható.")
        if row.get("missing_data"):
            warnings.append("Hiányzó adat: " + "; ".join(row.get("missing_data")[:2]))

        ideas.append(
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "sector": row.get("sector"),
                "category": cat,
                "stance": stance,
                "score": row.get("score"),
                "latest_price": round(price, 2),
                "target_price": round(fair_target, 2),
                "ai_target_price": round(ai_target, 2),
                "target_upside_pct": round(upside_pct, 2) if upside_pct is not None else None,
                "entry_to_target_pct": round(((fair_target / entry_price) - 1) * 100, 2) if entry_price else None,
                "target_source": target_source,
                "analyst_target_consensus": round(float(consensus), 2) if consensus else None,
                "analyst_target_high": round(float(analyst_high), 2) if analyst_high else None,
                "analyst_target_low": round(float(analyst_low), 2) if analyst_low else None,
                "analyst_target_median": round(float(analyst_median), 2) if analyst_median else None,
                "analyst_display_price": round(float(consensus), 2) if consensus else round(ai_target, 2),
                "analyst_display_label": "elemzői átlag" if consensus else "Tőzsde AI becslés",
                "entry_low": round(entry_low, 2),
                "entry_high": round(entry_high, 2),
                "entry_price": round(entry_price, 2),
                "exit_price": round(fair_target, 2),
                "review_down": round(review_down, 2),
                "is_short_signal": bool(is_short_signal),
                "timing_score": timing_score,
                "timing_label": timing_label,
                "timing_flag": timing_flag,
                "year_high": round(float(year_high), 2) if year_high else None,
                "year_low": round(float(year_low), 2) if year_low else None,
                "year_range_position": round(float(year_range_pos), 3) if year_range_pos is not None else None,
                "ath_distance_pct": ath_distance_pct,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "warning": " ".join(warnings) if warnings else "Nincs külön magas kockázati jelzés.",
                "reason": row.get("consensus_summary") or row.get("decision"),
                "data_quality": row.get("data_quality"),
                "analyst_count": target.get("analyst_count") if isinstance(target, dict) else None,
            }
        )
    return ideas


def source_quality(site: str | None) -> dict:
    domain = (site or "").lower().strip()
    primary = ["sec.gov", "businesswire.com", "globenewswire.com", "prnewswire.com", "investor.", "ir."]
    established = ["reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com", "marketwatch.com", "barrons.com", "finance.yahoo.com", "morningstar.com"]
    opinion = ["seekingalpha.com", "zacks.com", "fool.com", "benzinga.com", "gurufocus.com", "fxempire.com", "investorplace.com", "247wallst.com", "investopedia.com"]
    if any(marker in domain for marker in primary):
        return {"tier": 3.0, "label": "elsődleges / hivatalos forrás", "class": "source-primary"}
    if any(marker in domain for marker in established):
        return {"tier": 2.3, "label": "megbízható pénzügyi sajtó", "class": "source-established"}
    if any(marker in domain for marker in opinion):
        return {"tier": 0.8, "label": "háttér / véleményes forrás", "class": "source-opinion"}
    return {"tier": 1.4, "label": "másodlagos strukturált hírforrás", "class": "source-secondary"}


def news_relevance(stock: dict, item: dict) -> float:
    text = f"{item.get('title') or ''} {item.get('text') or ''}".lower()
    symbol = str(stock.get("symbol") or "").lower().replace(".", "")
    name_tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z]{4,}", str(stock.get("name") or ""))
        if token.lower() not in {"incorporated", "corporation", "company", "limited", "class", "group", "holdings"}
    ]
    score = 0.0
    if symbol and re.search(rf"\b{re.escape(symbol)}\b", text.replace(".", "")):
        score += 2.0
    if name_tokens and any(token in text for token in name_tokens[:3]):
        score += 1.5
    if item.get("symbol") == stock.get("symbol"):
        score += 0.8
    return score


def prepare_news(stock: dict, news_items: list[dict]) -> list[dict]:
    prepared = []
    seen_titles: set[str] = set()
    for item in news_items:
        site = str(item.get("site") or "").lower()
        url = str(item.get("url") or "").lower()
        title_raw = str(item.get("title") or "")
        if stock.get("symbol") == "INTC" and "intel 471" in title_raw.lower():
            continue
        if "youtube.com" in site or "youtube.com" in url or "youtu.be" in url:
            continue
        if any(domain in site for domain in ["seekingalpha.com", "zacks.com", "247wallst.com", "fool.com", "investorplace.com"]):
            continue
        title_key = re.sub(r"[^a-z0-9]+", " ", title_raw.lower()).strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        quality = source_quality(item.get("site"))
        relevance = news_relevance(stock, item)
        row = {
            **item,
            "source_tier": quality["tier"],
            "source_label": quality["label"],
            "source_class": quality["class"],
            "relevance": relevance,
            "evidence_weight": round(quality["tier"] + relevance, 2),
        }
        row["title_hu"] = news_title_hu(stock, row)
        row["summary_hu"] = factual_news_summary(stock, row)
        row["interpretation"] = row["summary_hu"]
        prepared.append(row)
    prepared.sort(key=lambda row: (row["relevance"] > 0, row["evidence_weight"], row["source_tier"], row.get("published_at") or ""), reverse=True)
    relevant = [row for row in prepared if row["relevance"] > 0]
    selected = relevant or prepared[:1]
    credible = [row for row in selected if float(row.get("source_tier", 0)) >= 1.4]
    return dedupe_news_rows(credible or selected)[:4]


def dedupe_news_rows(rows: list[dict]) -> list[dict]:
    selected = []
    seen = set()
    for row in rows:
        key = re.sub(r"[^a-z0-9]+", " ", str(row.get("title") or row.get("title_hu") or "").lower()).strip()
        summary_key = re.sub(r"\s+", " ", str(row.get("summary_hu") or "").lower()).strip()
        compound = key or summary_key
        if not compound or compound in seen:
            continue
        seen.add(compound)
        selected.append(row)
    return selected


def useful_excerpt(text: str, title: str, max_len: int = 220) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    title_words = set(re.findall(r"[a-zA-Z]{5,}", title.lower()))
    for sentence in re.split(r"(?<=[.!?])\s+", clean):
        sentence = sentence.strip()
        if len(sentence) < 55:
            continue
        sentence_words = set(re.findall(r"[a-zA-Z]{5,}", sentence.lower()))
        if title_words and len(title_words & sentence_words) / max(1, len(title_words)) > 0.72:
            continue
        return sentence[:max_len].rstrip(" ,;:-") + ("..." if len(sentence) > max_len else "")
    return clean[:max_len].rstrip(" ,;:-") + ("..." if len(clean) > max_len else "")


def extract_money_or_percent(text: str) -> str:
    matches = re.findall(r"(?:\$|USD\s*)\d[\d,.]*|\d+(?:\.\d+)?%", text)
    return matches[0] if matches else ""


def news_title_hu(stock: dict, item: dict) -> str:
    symbol = stock.get("symbol", "A részvény")
    name = str(stock.get("name") or symbol)
    title = str(item.get("title") or "")
    lower = title.lower()
    figure = extract_money_or_percent(title)
    suffix = f" ({figure})" if figure else ""
    if "launches" in lower:
        launched = re.split(r"\b[Ll]aunches\b", title, maxsplit=1)[-1].strip(" :-")
        return f"{symbol}: {name} új terméket vagy szolgáltatást indított" + (f" - {launched[:90]}" if launched else "")
    if has_any_news_keyword(lower, ["stock jumps", "stock rises", "shares jump", "shares rise", "surges", "rallies"]):
        return f"{symbol}: a részvény emelkedett a friss hír után{suffix}"
    if "investor conference" in lower or "investor conferences" in lower:
        return f"{symbol}: a vállalat befektetői konferencián vesz részt"
    if has_any_news_keyword(lower, ["stock falls", "stock drops", "shares fall", "shares drop", "slides", "slumps"]):
        return f"{symbol}: a részvény esett a friss hír után{suffix}"
    if has_any_news_keyword(lower, ["cuts", "reduces"]) and figure:
        return f"{symbol}: a vállalat csökkentést jelentett be{suffix}"
    if has_any_news_keyword(lower, ["price target", "upgrade", "downgrade", "analyst", "rating", "initiates"]):
        return f"{symbol}: elemzői célár- vagy ajánlásfrissítés{suffix}"
    if has_any_news_keyword(lower, ["earnings", "results", "quarter", "revenue", "eps", "guidance"]):
        return f"{symbol}: eredmény- vagy guidance-hír érkezett{suffix}"
    if has_any_news_keyword(lower, ["dividend", "buyback", "repurchase"]):
        return f"{symbol}: tőkevisszajuttatási hír"
    if has_any_news_keyword(lower, ["contract", "order", "backlog", "partnership", "deal", "award"]):
        return f"{symbol}: új szerződés vagy stratégiai megállapodás"
    if has_any_news_keyword(lower, ["lawsuit", "probe", "investigation", "regulator", "antitrust"]):
        return f"{symbol}: jogi vagy szabályozási kockázat"
    if has_any_news_keyword(lower, ["prior authorization", "healthcare", "coverage", "affordable", "transparency", "accountability"]):
        return f"{symbol}: egészségügyi működési és szabályozási hír"
    if has_any_news_keyword(lower, ["ai", "artificial intelligence", "chip", "semiconductor", "data center", "cloud"]):
        return f"{symbol}: AI-, chip- vagy adatközponti hír"
    if has_any_news_keyword(lower, ["oil", "gas", "crude", "opec", "drilling", "lng"]):
        return f"{symbol}: energiaárhoz vagy kitermeléshez kapcsolódó hír"
    if has_any_news_keyword(lower, ["fda", "trial", "approval", "pipeline", "clinical"]):
        return f"{symbol}: gyógyszerpipeline- vagy engedélyezési hír"
    if has_any_news_keyword(lower, ["trending", "talking about", "betting", "buying opportunity", "watchlist"]):
        return f"{symbol}: erősödő piaci figyelem"
    return f"{symbol}: friss vállalati hír"


def factual_news_summary(stock: dict, item: dict) -> str:
    symbol = stock.get("symbol", "A részvény")
    name = str(stock.get("name") or symbol)
    title = str(item.get("title") or "").strip()
    text = str(item.get("text") or "").strip()
    lower = f"{title} {text}".lower()
    figure = extract_money_or_percent(f"{title} {text}")
    source = str(item.get("site") or "a forrás")

    if has_any_news_keyword(lower, ["first quarter", "q1", "quarter 2026 results", "quarterly results", "results"]):
        return f"{name} friss negyedéves eredményközlést tett közzé. Forrás: {source}."
    if "prior authorization" in lower and figure:
        return f"UnitedHealthcare {figure}-kal csökkenti az előzetes engedélyezési követelményeket. Ez konkrét működési változás az egészségügyi adminisztrációban. Forrás: {source}."
    if "foundry" in lower and "apple" in lower:
        return f"A hír Apple-hez kapcsolódó Intel foundry-tárgyalásokról szól, és az Intel részvénye a cím szerint nagyot emelkedett. Forrás: {source}."
    if "investor conference" in lower or "investor conferences" in lower:
        return f"{name} befektetői konferencián való részvételt jelentett be. Ez vállalati kommunikációs esemény, nem eredményjelentés. Forrás: {source}."
    if "launches" in lower:
        product = re.split(r"\b[Ll]aunches\b", title, maxsplit=1)[-1].strip(" .:-")
        return f"{name} új terméket vagy szolgáltatást jelentett be" + (f": {product[:150]}." if product else f". Forrás: {source}.")
    if has_any_news_keyword(lower, ["contract", "award", "partnership", "deal"]):
        return f"{name} szerződéshez, partneri megállapodáshoz vagy üzleti együttműködéshez kapcsolódó hírt kapott. Forrás: {source}."
    if has_any_news_keyword(lower, ["dividend", "buyback", "repurchase"]):
        return f"{name} tőkevisszajuttatáshoz kapcsolódó hírt közölt, például osztalékot vagy részvény-visszavásárlást. Forrás: {source}."
    if has_any_news_keyword(lower, ["fda", "clinical", "trial", "approval", "phase"]):
        return f"{name} gyógyszerfejlesztési, klinikai vagy engedélyezési hírben szerepel. Forrás: {source}."
    if has_any_news_keyword(lower, ["lawsuit", "probe", "investigation", "regulator", "antitrust"]):
        return f"{name} jogi, vizsgálati vagy szabályozási hírben szerepel. Forrás: {source}."
    if has_any_news_keyword(lower, ["stock jumps", "stock rises", "shares jump", "shares rise", "surges", "rallies"]):
        return f"{name} részvénye emelkedett a hír megjelenésekor" + (f" ({figure})." if figure else ".") + f" Forrás: {source}."
    if has_any_news_keyword(lower, ["stock falls", "stock drops", "shares fall", "shares drop", "slides", "slumps"]):
        return f"{name} részvénye esett a hír megjelenésekor" + (f" ({figure})." if figure else ".") + f" Forrás: {source}."
    excerpt = useful_excerpt(text, title, 180)
    if excerpt:
        return f"A forrás ezt a vállalati eseményt közölte: {title}."
    return f"A hír tárgya: {title}. Forrás: {source}."


def has_news_keyword(text: str, keyword: str) -> bool:
    if " " in keyword:
        return keyword in text
    return bool(re.search(rf"\b{re.escape(keyword)}\b", text))


def has_any_news_keyword(text: str, keywords: list[str]) -> bool:
    return any(has_news_keyword(text, keyword) for keyword in keywords)


def news_driver(symbol: str, sector: str, lower: str) -> str:
    if has_any_news_keyword(lower, ["prior authorization", "coverage", "healthcare", "affordable", "transparency", "accountability"]):
        return "Egészségügyi működési hír: a befektetői érték azon múlik, hogy a változás csökkenti-e a szabályozási/reputációs nyomást, vagy inkább a marginokat terheli."
    if sector == "Healthcare" and has_any_news_keyword(lower, ["ai", "artificial intelligence", "automation"]):
        return "AI-alapú működési hatékonysági hír: egészségügyi cégnél ez nem AI-növekedési sztori, hanem költségszintet, kárrendezési sebességet és marginvédelmet érinthet."
    themes = [
        (
            ["earnings", "results", "quarter", "revenue", "eps", "guidance", "margin"],
            "Eredményoldali katalizátor: azt kell nézni, hogy a bevétel, EPS, margin vagy guidance eltért-e az elemzői várakozástól; ez közvetlenül átárazhatja a következő negyedévek profitpályáját.",
        ),
        (
            ["price target", "upgrade", "downgrade", "analyst", "rating", "initiates", "raises target", "cuts target"],
            "Elemzői újraárazás: a célár vagy ajánlás változása akkor számít igazán, ha mögötte nem csak hangulat, hanem magasabb növekedési, margin- vagy cash-flow feltételezés áll.",
        ),
        (
            ["dividend", "buyback", "repurchase", "capital return"],
            "Tőkevisszajuttatási jelzés: osztalék vagy buyback esetén a piac azt árazza, hogy a menedzsment mennyire bízik a cash-flow tartósságában.",
        ),
        (
            ["ai", "artificial intelligence", "gpu", "chip", "semiconductor", "data center", "cloud"],
            "AI/chip keresleti hír: a lényeg az, hogy a hír növeli-e a rendelésállományt, kapacitáskihasználtságot vagy pricing powert; ez különösen a növekedési prémiumot mozgatja.",
        ),
        (
            ["contract", "order", "backlog", "partnership", "deal", "wins", "award"],
            "Szerződés vagy partneri hír: akkor értékes, ha javítja a bevételi láthatóságot, növeli a backlogot, vagy stratégiai belépőt ad egy fontos ügyfélhez/piacra.",
        ),
        (
            ["lawsuit", "probe", "investigation", "regulator", "regulatory", "antitrust", "tariff", "ban"],
            "Szabályozási vagy jogi kockázat: az árfolyamhatás a várható bírságon, üzleti korlátozáson és reputációs kockázaton múlik.",
        ),
        (
            ["oil", "gas", "crude", "opec", "drilling", "lng", "barrel"],
            "Energiaár-érzékeny hír: az olaj/gázár, kitermelési volumen és beruházási fegyelem közvetlenül befolyásolja a szabad cash-flow-t.",
        ),
        (
            ["fda", "trial", "drug", "approval", "pipeline", "phase", "clinical"],
            "Gyógyszerpipeline-hír: itt a bináris kockázat magasabb; engedélyezés, klinikai adat vagy piaci hozzáférés módosíthatja a hosszú távú bevételi pályát.",
        ),
        (
            ["debt", "bond", "cash flow", "free cash flow", "liquidity", "balance sheet"],
            "Mérleg- és cash-flow hír: azt jelzi, hogy javul vagy romlik-e a finanszírozási mozgástér, ami magasabb kamatkörnyezetben különösen fontos.",
        ),
        (
            ["trending", "talking about", "betting", "buying opportunity", "watch list", "watchlist"],
            "Piaci figyelemről szóló hír: ez inkább narratíva- és volumenjel, nem kemény fundamentális adat; a célárak, eredménytrend és friss ármozgás döntik el, van-e mögötte valódi átárazási ok.",
        ),
    ]
    for keywords, explanation in themes:
        if has_any_news_keyword(lower, keywords):
            return explanation
    if "Semiconductors" in sector or "Software" in sector or "Technology" in sector:
        return "Technológiai olvasat: a hír akkor fontos, ha konkrétan befolyásolja az AI-keresletet, felhős növekedést, marginokat vagy beruházási ciklust."
    if sector == "Energy":
        return "Energia szektoros olvasat: a hír értéke főleg a cash-flow, kitermelés, olaj/gázár és tőkefegyelem felől mérhető."
    if sector == "Healthcare":
        return "Egészségügyi olvasat: pipeline, engedélyezés, árazási nyomás és eredményláthatóság alapján érdemes értelmezni."
    return f"{symbol} szempontjából a hír akkor hasznos, ha konkrétan változtat a keresleti, profitabilitási, mérleg- vagy kockázati képen."


def interpret_news(stock: dict, item: dict) -> str:
    title = str(item.get("title") or "").strip()
    text = str(item.get("text") or "").strip()
    symbol = stock.get("symbol", "A részvény")
    sector = str(stock.get("sector") or "")
    combined = f"{title} {text}".lower()
    impact = news_driver(symbol, sector, combined)
    return impact


def demo_prices(symbol: str, days: int = 380) -> list[dict]:
    seed = int(hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    base = 18 + (seed % 240)
    drift = rng.uniform(-0.0022, 0.0028)
    volatility = rng.uniform(0.010, 0.050)
    today = date.today()
    price = float(base)
    rows: list[dict] = []
    for idx in range(days):
        day = today - timedelta(days=days - idx)
        if day.weekday() >= 5:
            continue
        seasonal = math.sin(idx / 13 + (seed % 11)) * volatility * 0.8
        ret = drift + seasonal + rng.gauss(0, volatility)
        open_price = price
        close = max(1.0, price * (1 + ret))
        high = max(open_price, close) * (1 + abs(rng.gauss(0, volatility / 2)))
        low = min(open_price, close) * (1 - abs(rng.gauss(0, volatility / 2)))
        rows.append(
            {
                "date": day.isoformat(),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(max(0.5, low), 2),
                "close": round(close, 2),
                "volume": int(500_000 + rng.random() * 12_000_000),
                "source": "preview_model",
            }
        )
        price = close
    return rows


def pct(a: float, b: float) -> float:
    return 0.0 if not b else (a / b) - 1


def category(score: float) -> str:
    if score >= 55:
        return "buy"
    if score > 45:
        return "hold"
    return "sell"


def category_class(value: str) -> str:
    return value.replace(" ", "-")


def action_rank(item: dict) -> tuple[int, float, float]:
    priority = {"buy": 4, "sell": 4, "hold": 1}
    conviction = abs(float(item["score"]) - 50)
    return (priority.get(item["category"], 0), conviction, float(item["score"]))


def ensure_minimum_signals(rows: list[dict], min_each: int = 5) -> None:
    """Guarantee at least `min_each` buys and `min_each` sells by relative ranking.

    The system scores 0-100 with 50 = hold. Natural distribution clusters around 50,
    so we promote the top-scoring stocks to 'buy' and the lowest-scoring to 'sell'
    even when their absolute score is close to neutral. The score itself remains
    visible so the user can see how strong the signal really is.
    """
    if not rows or len(rows) < min_each * 2:
        return

    sorted_rows = sorted(rows, key=lambda r: r.get("score", 0))
    buy_count = sum(1 for r in rows if r.get("category") == "buy")
    sell_count = sum(1 for r in rows if r.get("category") == "sell")

    if buy_count < min_each:
        candidates = [r for r in reversed(sorted_rows) if r.get("category") != "buy"]
        promote = candidates[: max(0, min_each - buy_count)]
        for row in promote:
            row["category"] = "buy"
            row["category_class"] = "buy"

    if sell_count < min_each:
        candidates = [r for r in sorted_rows if r.get("category") != "sell"]
        demote = candidates[: max(0, min_each - sell_count)]
        for row in demote:
            row["category"] = "sell"
            row["category_class"] = "sell"


def agent(name: str, score: float, thesis: str) -> dict:
    clean_score = round(max(0, min(100, score)), 1)
    return {"agent": name, "score": clean_score, "stance": category(clean_score), "thesis": thesis}


def _safe_float(value) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        cleaned = float(str(value).replace("%", "").replace(",", ""))
        if math.isnan(cleaned) or math.isinf(cleaned):
            return None
        return cleaned
    except (ValueError, TypeError):
        return None


def extract_fundamentals_data(full_quote: dict | None, latest_price: float) -> dict:
    """Pull real fundamentals from FMP full-quote payload with safe fallbacks.

    Returns a dict with: pe, eps, market_cap, year_high, year_low, price_avg_50, price_avg_200,
    avg_volume, year_range_position, earnings_date, days_to_earnings, shares_outstanding.
    All values may be None if the underlying API didn't return them.
    """
    fq = full_quote or {}
    pe = _safe_float(fq.get("pe"))
    eps = _safe_float(fq.get("eps"))
    market_cap = _safe_float(fq.get("marketCap") or fq.get("marketCapitalization"))
    year_high = _safe_float(fq.get("yearHigh"))
    year_low = _safe_float(fq.get("yearLow"))
    price_avg_50 = _safe_float(fq.get("priceAvg50"))
    price_avg_200 = _safe_float(fq.get("priceAvg200"))
    avg_volume = _safe_float(fq.get("avgVolume"))
    shares = _safe_float(fq.get("sharesOutstanding"))

    year_range_position = None
    if year_high is not None and year_low is not None and year_high > year_low:
        year_range_position = max(0.0, min(1.0, (latest_price - year_low) / (year_high - year_low)))

    earnings_date_raw = fq.get("earningsAnnouncement")
    earnings_date_iso = None
    days_to_earnings = None
    if earnings_date_raw:
        try:
            text = str(earnings_date_raw).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            earnings_date_iso = parsed.date().isoformat()
            days_to_earnings = (parsed.date() - date.today()).days
        except (ValueError, TypeError):
            earnings_date_iso = None

    return {
        "pe": pe,
        "eps": eps,
        "market_cap": market_cap,
        "year_high": year_high,
        "year_low": year_low,
        "price_avg_50": price_avg_50,
        "price_avg_200": price_avg_200,
        "avg_volume": avg_volume,
        "year_range_position": year_range_position,
        "earnings_date": earnings_date_iso,
        "days_to_earnings": days_to_earnings,
        "shares_outstanding": shares,
    }


SECTOR_PE_BASELINE = {
    "Semiconductors": 28,
    "Software": 35,
    "Cloud / AI infrastructure": 38,
    "AI / Cloud": 38,
    "Technology": 30,
    "Communication Services": 22,
    "Healthcare": 22,
    "Pharma": 20,
    "Financials": 13,
    "Energy": 12,
    "Consumer": 24,
    "Consumer Discretionary": 28,
    "Consumer Staples": 22,
    "Industrials": 22,
    "Defense": 22,
    "Materials": 16,
    "Utilities": 18,
    "Real Estate": 20,
}


def sector_pe_baseline(sector: str | None) -> float:
    if not sector:
        return 22.0
    if sector in SECTOR_PE_BASELINE:
        return float(SECTOR_PE_BASELINE[sector])
    lower = sector.lower()
    for key, value in SECTOR_PE_BASELINE.items():
        if key.lower() in lower:
            return float(value)
    return 22.0


def compute_fundamentals_score(fund_data: dict, stock: dict, latest_price: float) -> tuple[float, list[str]]:
    """Real-data fundamentals score (0-100). Returns (score, reasoning_bullets).

    Inputs used: P/E vs sector baseline, EPS sign, price vs 50/200d MA (trend quality).
    """
    score = 50.0
    notes: list[str] = []
    sector = stock.get("sector") or ""

    pe = fund_data.get("pe")
    if pe is not None:
        baseline = sector_pe_baseline(sector)
        if pe <= 0:
            score -= 18
            notes.append(f"Veszteséges (P/E {pe:.1f}).")
        else:
            ratio = pe / baseline
            if ratio < 0.7:
                score += 22
                notes.append(f"P/E {pe:.1f} a szektor átlag alatt ({baseline:.0f}).")
            elif ratio < 1.0:
                score += 12
                notes.append(f"P/E {pe:.1f} a szektor átlaga alatt ({baseline:.0f}).")
            elif ratio < 1.3:
                score += 3
                notes.append(f"P/E {pe:.1f} a szektor átlag közelében ({baseline:.0f}).")
            elif ratio < 1.8:
                score -= 8
                notes.append(f"P/E {pe:.1f} drágább a szektor átlagánál ({baseline:.0f}).")
            else:
                score -= 18
                notes.append(f"P/E {pe:.1f} jelentősen drága a szektorhoz képest ({baseline:.0f}).")
    else:
        notes.append("Nincs publikált P/E adat.")

    eps = fund_data.get("eps")
    if eps is not None:
        if eps > 0:
            score += 9
            notes.append(f"Pozitív EPS: {eps:.2f}.")
        else:
            score -= 12
            notes.append(f"Negatív EPS: {eps:.2f} - profitabilitás nyomás alatt.")

    price_avg_50 = fund_data.get("price_avg_50")
    price_avg_200 = fund_data.get("price_avg_200")
    if price_avg_50 and price_avg_200 and latest_price:
        if latest_price > price_avg_50 > price_avg_200:
            score += 12
            notes.append("Ár > 50d MA > 200d MA: tartós feltrend, minőségi jel.")
        elif latest_price > price_avg_200 and price_avg_50 < price_avg_200:
            score += 3
            notes.append("Ár 200d MA felett, de a rövid trend gyengül.")
        elif latest_price < price_avg_50 < price_avg_200:
            score -= 12
            notes.append("Ár < 50d MA < 200d MA: tartós letrend.")
        elif latest_price < price_avg_200:
            score -= 6
            notes.append("Ár 200d MA alatt: gyenge hosszú távú trend.")

    return max(5.0, min(95.0, score)), notes


def compute_valuation_score(fund_data: dict, latest_price: float, stock: dict) -> tuple[float, list[str]]:
    """Real-data valuation score (0-100). Higher = better value entry. Returns (score, notes)."""
    score = 50.0
    notes: list[str] = []

    pos = fund_data.get("year_range_position")
    if pos is not None:
        if pos < 0.2:
            score += 26
            notes.append(f"Az árfolyam az 52-hetes mélypont közelében ({pos*100:.0f}%): erős értékeltségi szint, de fundamentummal validálni.")
        elif pos < 0.4:
            score += 14
            notes.append(f"Az árfolyam az 52-hetes sáv alsó harmadában ({pos*100:.0f}%): kedvező belépési zóna.")
        elif pos < 0.6:
            score += 3
            notes.append(f"Az árfolyam az 52-hetes sáv közepén ({pos*100:.0f}%).")
        elif pos < 0.85:
            score -= 8
            notes.append(f"Az árfolyam a sáv felső felében ({pos*100:.0f}%): drágább belépő.")
        else:
            score -= 18
            notes.append(f"Az árfolyam az 52-hetes csúcs közelében ({pos*100:.0f}%): túlfeszített belépő.")
    else:
        notes.append("Nincs 52-hetes árfolyam-sáv adat.")

    pe = fund_data.get("pe")
    sector = stock.get("sector") or ""
    if pe is not None and pe > 0:
        baseline = sector_pe_baseline(sector)
        ratio = pe / baseline
        if ratio < 0.8:
            score += 15
            notes.append("P/E olcsó a szektorhoz képest: értékeltségi bónusz.")
        elif ratio > 1.5:
            score -= 12
            notes.append("P/E drága a szektorhoz képest: értékeltségi büntetés.")

    price_avg_200 = fund_data.get("price_avg_200")
    if price_avg_200 and latest_price:
        gap = (latest_price / price_avg_200) - 1.0
        if gap > 0.25:
            score -= 9
            notes.append(f"Az ár {gap*100:.0f}%-kal a 200d MA felett: trendi prémium.")
        elif gap < -0.15:
            score += 7
            notes.append(f"Az ár {abs(gap)*100:.0f}%-kal a 200d MA alatt: lehetséges visszateszt.")

    return max(5.0, min(95.0, score)), notes


def compute_events_score(news_items: list[dict], fund_data: dict, has_filings: bool = False) -> tuple[float, list[str]]:
    """Events/catalyst score (0-100). Includes news strength + earnings proximity. Returns (score, notes)."""
    score = 50.0
    notes: list[str] = []

    news_strength = sum(float(item.get("source_tier", 1.0)) for item in (news_items or [])[:3])
    if news_strength >= 5:
        score += 12
        notes.append("Magas minőségű friss hírforrás-keverék.")
    elif news_strength >= 3:
        score += 6
        notes.append("Megbízható forrásokból érkező hírek.")
    elif news_strength > 0:
        score += 2
    else:
        score -= 6
        notes.append("Nincs friss strukturált hír; gyenge esemény-jelzés.")

    days_to_earnings = fund_data.get("days_to_earnings")
    if days_to_earnings is not None:
        if 0 <= days_to_earnings <= 7:
            score += 8
            notes.append(f"Eredményközlés {days_to_earnings} napon belül - közvetlen katalizátor.")
        elif 0 <= days_to_earnings <= 21:
            score += 4
            notes.append(f"Eredményközlés {days_to_earnings} napon belül - közelgő katalizátor.")
        elif days_to_earnings < 0 and days_to_earnings >= -7:
            score += 2
            notes.append(f"Eredményközlés volt {abs(days_to_earnings)} napja - friss eredmény-háttér.")

    return max(10.0, min(90.0, score)), notes


def agent_debate(
    symbol: str,
    momentum: float,
    fundamentals: float,
    valuation: float,
    events: float,
    risk: float,
    fund_data: dict,
    fund_notes: list[str],
    val_notes: list[str],
    events_notes: list[str],
    missing_data: list[str],
) -> list[dict]:
    """Genuine agent divergence - each agent weights different real inputs."""

    def short(notes: list[str], default: str) -> str:
        if not notes:
            return default
        return " ".join(str(n) for n in notes[:2])

    trend_score = momentum * 0.85 + risk * 0.15
    trend_thesis = (
        f"Csak az árfolyam-trend és a volatilitás számít. "
        f"Momentum komponens: {momentum:.0f}, kockázati háttér: {risk:.0f}. "
    )
    price_avg_50 = fund_data.get("price_avg_50")
    price_avg_200 = fund_data.get("price_avg_200")
    if price_avg_50 and price_avg_200:
        if price_avg_50 > price_avg_200:
            trend_thesis += "Az 50d MA a 200d felett: feltrend érvényben."
        else:
            trend_thesis += "Az 50d MA a 200d alatt: lefelé tartó középtáv."

    fundamentalist_score = fundamentals * 0.8 + (events * 0.2 if fund_data.get("days_to_earnings") is None or fund_data["days_to_earnings"] > 21 else events * 0.1 + fundamentals * 0.1)
    fundamentalist_thesis = f"Csak a profitabilitás és a növekedés. {short(fund_notes, 'Nincs elég publikált adat')}."

    value_score = valuation * 0.9 + (10 if fund_data.get("year_range_position") is not None and fund_data["year_range_position"] < 0.3 else 0)
    value_thesis = f"Csak a belépési ár és értékeltség. {short(val_notes, 'Nincs elég ár-sáv adat')}."

    sentiment_score = events * 0.7 + momentum * 0.3
    sentiment_thesis = f"Friss hírek és piaci hangulat. {short(events_notes, 'Nincs erős hír-jelzés')}."

    bear_inputs = [valuation, risk, fundamentals]
    bear_score = min(bear_inputs) * 0.6 + (50 - abs(fmean(bear_inputs) - 50)) * 0.4
    bear_score = max(0, min(100, 100 - bear_score))  # Bear score = how strong the bear case is
    bear_notes_text = []
    if fund_data.get("year_range_position") is not None and fund_data["year_range_position"] > 0.85:
        bear_notes_text.append("52-hetes csúcs közelében - korrekció kockázata.")
    if fund_data.get("pe") is not None and fund_data["pe"] > 0:
        baseline = sector_pe_baseline(symbol)
        if fund_data["pe"] / baseline > 1.5:
            bear_notes_text.append("P/E drága a szektorhoz képest.")
    if risk < 40:
        bear_notes_text.append(f"Gyenge kockázati pont ({risk:.0f}): volatilitás vagy drawdown.")
    if not bear_notes_text:
        bear_notes_text.append("A jelenlegi adatokban nincs domináns bear érv.")
    bear_thesis = "Csak a kockázatok és túlárazás. " + " ".join(bear_notes_text[:2])
    # Convert bear score: high bear-case strength = LOW agent score (because agent_score is bullishness)
    bear_agent_score = max(0, min(100, 100 - bear_score))

    risk_score = risk * 0.85 + (50 - abs(momentum - 50)) * 0.15
    risk_thesis = f"Csak a volatilitás, drawdown, hiányzó adatok. Kockázati pont: {risk:.0f}; hiányzó komponens: {len(missing_data)}."

    agents = [
        agent("Trend Analyst", trend_score, trend_thesis.strip()),
        agent("Fundamental Analyst", fundamentalist_score, fundamentalist_thesis.strip()),
        agent("Value Hunter", value_score, value_thesis.strip()),
        agent("Sentiment Analyst", sentiment_score, sentiment_thesis.strip()),
        agent("Bear Researcher", bear_agent_score, bear_thesis.strip()),
        agent("Risk Manager", risk_score, risk_thesis.strip()),
    ]

    scores = [a["score"] for a in agents]
    pm_score = fmean(scores)
    divergence = max(scores) - min(scores)
    if divergence > 25:
        pm_thesis = (
            f"Az agentek véleménye jelentősen eltér ({divergence:.0f} pont szórás). "
            f"Konszenzus: {category(pm_score)}; az eltérés miatt kis pozícióval érdemes kezdeni."
        )
    elif divergence > 12:
        pm_thesis = (
            f"Mérsékelt eltérés az agentek között ({divergence:.0f} pont). "
            f"Konszenzus: {category(pm_score)}."
        )
    else:
        pm_thesis = (
            f"Az agentek nagyrészt egyetértenek (eltérés {divergence:.0f} pont). "
            f"Egységes jelzés: {category(pm_score)}."
        )
    agents.append(agent("Portfolio Manager", pm_score, pm_thesis))
    return agents


def position_size_suggestion(score: float, cat: str, risk_score: float, fund_data: dict, conviction: float) -> dict:
    """Position size recommendation tailored to a 10-20 holding portfolio, min 2%.

    Returns: {recommended_pct, range_low, range_high, rationale, label}
    """
    market_cap = fund_data.get("market_cap")
    is_mega = market_cap is not None and market_cap >= 500e9
    is_large = market_cap is not None and 50e9 <= market_cap < 500e9
    is_mid = market_cap is not None and 2e9 <= market_cap < 50e9
    is_small = market_cap is not None and market_cap < 2e9

    if cat == "sell":
        return {
            "recommended_pct": 0.0,
            "range_low": 0.0,
            "range_high": 0.0,
            "label": "Kerülendő / trimmel",
            "rationale": "A jelzés a kockázat/hozam profilt kedvezőtlennek mutatja. Új pozíció nem indokolt; meglévő esetén csökkentés mérlegelendő.",
        }
    if cat == "hold":
        return {
            "recommended_pct": 0.0,
            "range_low": 0.0,
            "range_high": 0.0,
            "label": "Csak figyelőlista",
            "rationale": "Nincs erős hosszabb távú jelzés. Új pozíciót nem érdemes nyitni, amíg a kép tisztázódik (eredmény, célár revízió).",
        }

    high_conviction = conviction >= 12
    if cat == "buy" and high_conviction and risk_score >= 60 and is_mega:
        low, high = 10.0, 15.0
    elif cat == "buy" and high_conviction and risk_score >= 55 and is_large:
        low, high = 7.0, 10.0
    elif cat == "buy" and high_conviction and is_mid:
        low, high = 4.0, 6.0
    elif cat == "buy" and high_conviction:
        low, high = 3.0, 5.0
    elif cat == "buy" and risk_score >= 60 and is_mega:
        low, high = 6.0, 10.0
    elif cat == "buy" and risk_score >= 55 and is_large:
        low, high = 4.0, 7.0
    elif cat == "buy" and is_mid:
        low, high = 3.0, 5.0
    elif cat == "buy":
        low, high = 2.0, 4.0
    else:
        low, high = 2.0, 3.0

    if risk_score < 40:
        low = max(2.0, low - 1.0)
        high = max(low + 1.0, high - 2.0)
    if conviction < 10:
        high = max(low + 0.5, high - 1.0)

    recommended = round((low + high) / 2, 1)
    low_r = round(low, 1)
    high_r = round(high, 1)

    if recommended >= 10:
        label = "Mag pozíció (core)"
        rationale = "Mega-cap minőség, erős jelzés és alacsony adatkockázat. Portfolio mag-pozíciónak jelölhető, de fokozatos beszállással."
    elif recommended >= 5:
        label = "Standard pozíció"
        rationale = "Megbízható minőség és kedvező belépés. Standard méretű pozícióként kezelhető a portfolió diverzifikált részeként."
    elif recommended >= 3:
        label = "Kisebb pozíció"
        rationale = "Még tartható jelzés, de magasabb kockázattal vagy gyengébb adatháttérrel. Csak kisebb sizinggel."
    else:
        label = "Minimális próba"
        rationale = "Csak induló próbapozíció. Ha 2% alá esne a méret, inkább érdemes kihagyni és más ötletre koncentrálni."

    return {
        "recommended_pct": recommended,
        "range_low": low_r,
        "range_high": high_r,
        "label": label,
        "rationale": rationale,
    }


def score_stock(stock: dict, quote: dict | None, news_items: list[dict], env: dict[str, str], historical_prices: list[dict] | None = None, full_quote: dict | None = None, previous_score: float | None = None) -> dict:
    news_items = prepare_news(stock, news_items)
    if historical_prices and len(historical_prices) >= 60:
        prices = [dict(row) for row in historical_prices]
        history_source = str(prices[-1].get("source") or "")
        price_source = "Yahoo Finance valós napi idősor" if history_source.startswith("yahoo") else "FMP valós napi történeti idősor"
    else:
        prices = demo_prices(stock["symbol"])
        price_source = "modellált idősor"
    quote_change = None
    quote_change_pct = None
    quote_volume = None
    if quote and quote.get("price"):
        live_price = float(quote["price"])
        if historical_prices and len(historical_prices) >= 60:
            today_key = date.today().isoformat()
            if prices and prices[-1]["date"] == today_key:
                prices[-1]["close"] = round(live_price, 2)
                prices[-1]["high"] = round(max(float(prices[-1].get("high") or live_price), live_price), 2)
                prices[-1]["low"] = round(min(float(prices[-1].get("low") or live_price), live_price), 2)
                prices[-1]["source"] = "fmp_historical_eod_plus_quote"
            elif prices and prices[-1]["date"] < today_key:
                previous = prices[-1]
                prices.append(
                    {
                        "date": today_key,
                        "open": round(float(previous["close"]), 2),
                        "high": round(max(float(previous["close"]), live_price), 2),
                        "low": round(min(float(previous["close"]), live_price), 2),
                        "close": round(live_price, 2),
                        "volume": int(float(quote.get("volume") or 0)),
                        "source": "fmp_quote",
                    }
                )
            price_source = f"{price_source} + élő quote"
        else:
            factor = live_price / prices[-1]["close"] if prices[-1]["close"] else 1
            for row in prices:
                row["open"] = round(row["open"] * factor, 2)
                row["high"] = round(row["high"] * factor, 2)
                row["low"] = round(row["low"] * factor, 2)
                row["close"] = round(row["close"] * factor, 2)
            prices[-1]["close"] = round(live_price, 2)
            prices[-1]["source"] = "fmp_quote"
            price_source = "FMP élő quote + modellált előzmény"
        for source_key, target in (("change", "quote_change"), ("changesPercentage", "quote_change_pct"), ("volume", "quote_volume")):
            raw = quote.get(source_key)
            if raw in (None, ""):
                continue
            try:
                value = float(str(raw).replace("%", ""))
            except ValueError:
                continue
            if target == "quote_change":
                quote_change = value
            elif target == "quote_change_pct":
                quote_change_pct = value
            else:
                quote_volume = value

    closes = [row["close"] for row in prices]
    latest = closes[-1]
    previous_close = closes[-2] if len(closes) >= 2 else latest
    fallback_change = latest - previous_close
    fallback_change_pct = pct(latest, previous_close) * 100 if previous_close else 0
    if quote_change_pct is not None:
        latest_change_pct = quote_change_pct
        implied_previous = latest / (1 + quote_change_pct / 100) if quote_change_pct != -100 else previous_close
        implied_change = latest - implied_previous
        if quote_change is None or (quote_change and implied_change and (quote_change > 0) != (implied_change > 0)):
            latest_change = implied_change
        else:
            latest_change = quote_change
    else:
        if quote_change is not None and fallback_change and (quote_change > 0) != (fallback_change > 0):
            latest_change = fallback_change
        else:
            latest_change = quote_change if quote_change is not None else fallback_change
        latest_change_pct = fallback_change_pct
    ma20 = fmean(closes[-20:])
    ma50 = fmean(closes[-50:])
    ma200 = fmean(closes[-200:]) if len(closes) >= 200 else fmean(closes)
    momentum = max(0, min(100, 50 + pct(latest, ma20) * 95 + pct(ma20, ma50) * 105 + pct(ma50, ma200) * 75))

    fund_data = extract_fundamentals_data(full_quote, latest)
    fundamentals, fund_notes = compute_fundamentals_score(fund_data, stock, latest)
    valuation, val_notes = compute_valuation_score(fund_data, latest, stock)
    events, events_notes = compute_events_score(news_items, fund_data)

    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1]]
    vol = pstdev(returns[-60:]) if len(returns) > 2 else 0
    peak = max(closes[-120:])
    drawdown = pct(latest, peak)
    risk = max(0, min(100, 78 - vol * 560 + drawdown * 55))

    weighted = round(momentum * 0.12 + fundamentals * 0.34 + valuation * 0.24 + events * 0.10 + risk * 0.20, 1)
    missing_data = []
    if "modellált" in price_source:
        missing_data.append("Nincs teljes valós történeti napi árfolyam-idősor; fallback modellált idősorral számol.")
    if not env.get("FMP_API_KEY"):
        missing_data.append("FMP kulcs hiányzik; fundamentum/célár komponens fallback módban van.")
    if not news_items:
        missing_data.append("Nincs friss strukturált hír ehhez a tickerhez.")
    if fund_data.get("pe") is None and fund_data.get("eps") is None:
        missing_data.append("Nincs publikált P/E vagy EPS adat; fundamentum-jel csak ár-alapú.")

    agents = agent_debate(stock["symbol"], momentum, fundamentals, valuation, events, risk, fund_data, fund_notes, val_notes, events_notes, missing_data)
    agent_score = fmean(item["score"] for item in agents)
    score = round(max(0, min(100, weighted * 0.72 + agent_score * 0.28)), 1)
    cat = category(score)
    conviction = round(abs(score - 50), 1)

    score_change = None
    if previous_score is not None:
        score_change = round(score - previous_score, 1)

    position_size = position_size_suggestion(score, cat, risk, fund_data, conviction)

    horizon_text = "1-2 éves távon"
    high_conv = conviction >= 12
    if cat == "buy" and high_conv:
        decision = f"{horizon_text} erős vételi jelzés ({score:.0f}/100 pont) - magas konvikcióval vizsgálandó pozíció."
    elif cat == "buy":
        decision = f"{horizon_text} vételi oldalon vizsgálandó ötlet ({score:.0f}/100 pont) - érdemes belépési pontot keresni."
    elif cat == "hold":
        decision = f"Semleges jelzés ({score:.0f}/100 pont, 50 = közömbös). Figyelőlistán tartandó, új pozíció nyitása előtt érdemes várni katalizátorra."
    elif cat == "sell" and high_conv:
        decision = f"{horizon_text} erős negatív jelzés ({score:.0f}/100 pont) - új pozíció nem indokolt, meglévő csökkentése mérlegelendő."
    else:
        decision = f"{horizon_text} gyenge kockázat/hozam profil ({score:.0f}/100 pont) - meglévő pozíció felülvizsgálata indokolt."

    bull_points: list[str] = []
    bear_points: list[str] = []
    for note in fund_notes + val_notes + events_notes:
        if any(token in note.lower() for token in ["alatt", "alsó", "pozitív", "feltrend", "kedvező", "katalizátor", "minőségi", "olcsó", "bónusz", "friss eredmény"]):
            bull_points.append(note)
        elif any(token in note.lower() for token in ["drága", "drágább", "felső", "csúcs", "letrend", "gyengül", "veszteséges", "büntetés", "túlfeszített", "negatív", "nincs"]):
            bear_points.append(note)
    reasons = [
        f"Jelzés: {cat} ({score:.1f} pont, konvikció {conviction:.1f}). Komponensek - momentum {momentum:.0f}, fundamentum {fundamentals:.0f}, értékeltség {valuation:.0f}, esemény {events:.0f}, kockázat {risk:.0f}.",
    ]
    if bull_points:
        reasons.append("Vételi érvek: " + " ".join(bull_points[:3]))
    if bear_points:
        reasons.append("Óvatossági érvek: " + " ".join(bear_points[:3]))
    reasons.append(f"Adatforrás: {price_source}.")

    risks = []
    if vol > 0.035:
        risks.append(f"Magas rövid távú volatilitás ({vol*100:.1f}% napi szórás).")
    if drawdown < -0.2:
        risks.append(f"Jelentős visszaesés a közelmúlt csúcsától: {drawdown:.1%}.")
    if fund_data.get("year_range_position") is not None and fund_data["year_range_position"] > 0.9:
        risks.append("52-hetes csúcs közelében: korrekciós kockázat.")
    if fund_data.get("pe") is not None and fund_data["pe"] > 0:
        baseline = sector_pe_baseline(stock.get("sector") or "")
        if fund_data["pe"] / baseline > 1.6:
            risks.append(f"P/E {fund_data['pe']:.1f} jelentősen drága a szektorhoz ({baseline:.0f}) képest.")
    if not news_items:
        risks.append("Friss hír nélkül az eseménykomponens óvatosabb.")
    if not risks:
        risks.append("Nincs kiugró kockázati jel a jelenlegi adatok alapján.")

    evidence_items = build_evidence_items(stock, cat, quote, news_items, prices, momentum, valuation, events, risk, risks, missing_data)
    data_quality = 100
    if "modellált" in price_source:
        data_quality -= 35
    if not news_items:
        data_quality -= 14
    data_quality -= min(30, max(0, len(missing_data) - 1) * 10)
    source_bonus = sum(float(item.get("source_tier", 1.0)) for item in news_items[:3])
    data_quality = round(max(0, min(100, data_quality + min(8, source_bonus * 1.5))), 1)
    if data_quality >= 80:
        data_quality_label = "magas adatbizalom"
    elif data_quality >= 55:
        data_quality_label = "közepes adatbizalom"
    else:
        data_quality_label = "alacsony adatbizalom"
    consensus_summary = " ".join(evidence_items[:3])
    article = build_article(stock, cat, score, decision, reasons, risks, news_items, price_source)
    return {
        **stock,
        "score": score,
        "score_change": score_change,
        "category": cat,
        "category_class": category_class(cat),
        "conviction": conviction,
        "decision": decision,
        "consensus_summary": consensus_summary,
        "evidence_items": evidence_items,
        "components": {
            "momentum": round(momentum, 1),
            "fundamentals": round(fundamentals, 1),
            "valuation": round(valuation, 1),
            "events": round(events, 1),
            "risk": round(risk, 1),
        },
        "fundamentals_data": fund_data,
        "position_size": position_size,
        "agent_debate": agents,
        "reasons": reasons,
        "risks": risks[:4],
        "missing_data": missing_data,
        "data_quality": data_quality,
        "data_quality_label": data_quality_label,
        "prices": prices[-5:],
        "latest_price": latest,
        "latest_change": round(latest_change, 2),
        "latest_change_pct": round(latest_change_pct, 2),
        "latest_volume": quote_volume,
        "price_source": price_source,
        "price_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "news": news_items[:3],
        "article": article,
        "modelled_data_warning": "modellált" in price_source,
    }


def build_evidence_items(
    stock: dict,
    cat: str,
    quote: dict | None,
    news_items: list[dict],
    prices: list[dict],
    momentum: float,
    valuation: float,
    events: float,
    risk: float,
    risks: list[str],
    missing_data: list[str],
) -> list[str]:
    sector = stock.get("sector") or "Ismeretlen"
    items: list[str] = []
    price_fact = quote_fact(quote, prices)
    if price_fact:
        items.append(price_fact)

    items.append(short_sector_driver(sector))

    signal = signal_fact(cat, momentum, valuation, events, risk)
    if signal:
        items.append(signal)

    risk_text = str(risks[0]).rstrip(".") if risks else "nincs külön jelölt kockázat"
    items.append(f"Kockázat: {risk_text}.")

    if missing_data:
        items.append(f"Adatminőség: {len(missing_data)} hiányos komponens, ezért a jelzés óvatosabban kezelendő.")
    return items[:6]


def quote_fact(quote: dict | None, prices: list[dict]) -> str | None:
    if quote and quote.get("price") not in (None, ""):
        price = float(quote.get("price"))
        pct_value = quote.get("changesPercentage") or quote.get("changePercentage") or quote.get("changes_percentage")
        change_value = quote.get("change")
        volume = quote.get("volume")
        previous_close = prices[-2]["close"] if len(prices) >= 2 else price
        fallback_change = price - previous_close
        fallback_pct = pct(price, previous_close) * 100 if previous_close else 0
        pct_clean = None
        change_clean = None
        if pct_value not in (None, ""):
            try:
                pct_clean = float(str(pct_value).replace("%", ""))
            except ValueError:
                pass
        if change_value not in (None, ""):
            try:
                change_clean = float(change_value)
            except ValueError:
                pass
        if pct_clean is not None:
            implied_previous = price / (1 + pct_clean / 100) if pct_clean != -100 else previous_close
            implied_change = price - implied_previous
            if change_clean is None or (change_clean and implied_change and (change_clean > 0) != (implied_change > 0)):
                change_clean = implied_change
        else:
            pct_clean = fallback_pct
            if change_clean is None or (change_clean and fallback_change and (change_clean > 0) != (fallback_change > 0)):
                change_clean = fallback_change
        parts = [f"Élő quote: {price:.2f} USD", f"napi változás {pct_clean:+.2f}%", f"árváltozás {change_clean:+.2f}"]
        if volume not in (None, ""):
            try:
                parts.append(f"volumen {int(float(volume)):,}".replace(",", " "))
            except ValueError:
                pass
        return "; ".join(parts) + "."
    if len(prices) >= 20:
        change_20 = pct(prices[-1]["close"], prices[-20]["close"])
        return f"Technikai proxy: teljes élő idősor nélkül, modellált előzmény alapján a 20 napos változás {change_20:+.1%}."
    return None


def short_sector_driver(sector: str) -> str:
    drivers = {
        "Technology": "Mozgatórugó: AI-beruházások, felhős kereslet, chipciklus és marzsok.",
        "Communication Services": "Mozgatórugó: reklámpiac, felhasználói növekedés, AI-infrastruktúra és szabályozás.",
        "Consumer Discretionary": "Mozgatórugó: fogyasztói kereslet, kamatkörnyezet, utazás/e-kereskedelem és árrés.",
        "Consumer Staples": "Mozgatórugó: árazási erő, volumen, inputköltség és osztalékstabilitás.",
        "Energy": "Mozgatórugó: olaj/gázár, kitermelési fegyelem, geopolitikai prémium és cash-flow.",
        "Healthcare": "Mozgatórugó: gyógyszerpipeline, engedélyezés, árazási nyomás és eredményláthatóság.",
        "Financials": "Mozgatórugó: hozamgörbe, hitelminőség, tőkekövetelmények és részvényesi hozam.",
        "Industrials": "Mozgatórugó: rendelésállomány, védelmi/energia-infrastruktúra beruházások és költségkontroll.",
        "Materials": "Mozgatórugó: fémárak, kínai kereslet, készletszintek és projektkockázat.",
        "Utilities": "Mozgatórugó: kamatszint, szabályozott hozam, energiaátmeneti beruházás és osztalékbiztonság.",
    }
    return drivers.get(sector, "Mozgatórugó: szektorszintű trend, eredményvárakozás, kockázati étvágy és likviditás.")


def signal_fact(cat: str, momentum: float, valuation: float, events: float, risk: float) -> str:
    positives = []
    negatives = []
    if momentum >= 65:
        positives.append("erős árfolyam-lendület")
    elif momentum <= 35:
        negatives.append("gyenge árfolyam-lendület")
    if valuation >= 65:
        positives.append("kedvezőbb értékeltségi kép")
    elif valuation <= 35:
        negatives.append("nyomott értékeltségi/proxy kép")
    if events >= 60:
        positives.append("aktív hír/esemény háttér")
    if risk >= 65:
        positives.append("kezelhető kockázati profil")
    elif risk <= 35:
        negatives.append("romló kockázati profil")

    if cat == "buy":
        basis = positives or ["a rangsorban relatíve kedvezőbb kockázat/hozam kép"]
        return f"Buy oldal: {', '.join(basis)} miatt került előre."
    elif cat == "sell":
        basis = negatives or ["a rangsorban gyengébb kockázat/hozam kép"]
        return f"Sell oldal: {', '.join(basis)} miatt került előre."
    mixed = positives[:2] + negatives[:2]
    return f"Hold ok: {', '.join(mixed) if mixed else 'nincs erős egyirányú katalizátor'}."


def sector_driver(sector: str) -> str:
    drivers = {
        "Technology": "A technológiai részvényeknél most az AI-költések, felhős növekedés, chipciklus és marzsnyomás mozgatja leginkább az árfolyamot.",
        "Communication Services": "A kommunikációs és média cégeknél a reklámpiaci lendület, felhasználói növekedés, AI-infrastruktúra költés és szabályozási kockázat a fő árfolyammozgató.",
        "Consumer Discretionary": "A fogyasztási ciklikus cégeknél a kereslet rugalmassága, reáljövedelem, utazási/e-kereskedelmi trend és kamatkörnyezet döntő.",
        "Consumer Staples": "A defenzív fogyasztási cégeknél az árazási erő, volumen, inputköltség és osztalékstabilitás mozgatja a befektetői képet.",
        "Energy": "Az energiaszektorban az olaj- és gázár, kitermelési fegyelem, geopolitikai prémium és cash-flow hozam a fő mozgató.",
        "Healthcare": "Az egészségügyben a pipeline, gyógyszerengedélyezés, árazási nyomás és eredményláthatóság határozza meg a befektetői narratívát.",
        "Financials": "A pénzügyi cégeknél a hozamgörbe, hitelminőség, tőkekövetelmények és részvényesi hozam a fő piacmozgató.",
        "Industrials": "Az ipari papíroknál a rendelésállomány, védelmi/energia-infrastruktúra beruházások, ciklikus kereslet és költségkontroll számít.",
        "Materials": "A nyersanyagcégeknél a fémárak, kínai kereslet, készletszintek és projektkockázat határozza meg a hangulatot.",
        "Utilities": "A közműcégeknél a kamatszint, szabályozott hozam, energiaátmeneti beruházás és osztalékbiztonság a fő mozgatórugó.",
    }
    return drivers.get(sector, "A papír árát főleg a szektorszintű trend, eredményvárakozás, kockázati étvágy és likviditási környezet mozgatja.")


def component_tone(momentum: float, valuation: float, events: float, risk: float) -> str:
    positives = []
    cautions = []
    if momentum >= 65:
        positives.append("az árfolyam lendülete támogató")
    elif momentum <= 35:
        cautions.append("az árfolyam lendülete gyenge")
    if valuation >= 65:
        positives.append("az értékeltségi kép kedvezőbb")
    elif valuation <= 35:
        cautions.append("az értékeltségi kép kevésbé vonzó")
    if events >= 60:
        positives.append("az eseményoldal élénkebb")
    if risk >= 65:
        positives.append("a kockázati profil kezelhető")
    elif risk <= 35:
        cautions.append("a kockázati profil romlott")

    if positives and cautions:
        return f"A pozitív oldal: {', '.join(positives)}; az óvatossági oldal: {', '.join(cautions)}."
    if positives:
        return f"A döntést támogató fő tényezők: {', '.join(positives)}."
    if cautions:
        return f"A döntést visszafogó fő tényezők: {', '.join(cautions)}."
    return "A komponensek vegyesek, ezért a döntés inkább relatív rangsor és kockázati kép alapján születik."


def build_article(stock: dict, cat: str, score: float, decision: str, reasons: list[str], risks: list[str], news_items: list[dict], price_source: str) -> dict:
    if news_items:
        lead = f"A legfrissebb strukturált hírek alapján {stock['symbol']} most {cat} besorolást kapott. A rendszer a hírfolyamot, az ármozgást és a kockázati képet együtt értékelte."
    else:
        lead = f"{stock['symbol']} esetében nincs friss strukturált hír a preview-adatban, ezért a napi jegyzet az árfolyam- és pontszám-komponensekre támaszkodik."
    bullets = [
        decision,
        reasons[1],
        f"Árfolyamforrás: {price_source}.",
        f"Fő kockázat: {risks[0]}",
    ]
    return {
        "title": f"Napi elemzés: {stock['symbol']} - {cat}",
        "lead": lead,
        "bullets": bullets,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "disclaimer": "Döntéstámogató elemzés, nem automatikus kereskedési utasítás.",
    }


def build_report(rows: list[dict], macro_news: list[dict]) -> dict:
    buy_items = [row for row in rows if row["category"] == "buy"][:8]
    sell_items = [row for row in rows if row["category"] == "sell"][:8]
    hold_items = [row for row in rows if row["category"] == "hold"][:8]
    if macro_news:
        macro_intro = (
            "A mai makrókép a friss strukturált hírfolyamból készült. "
            "A rendszer a nagy piaci mozgatórugókat először általános piaci szinten nézi, csak utána tér át az egyedi tickerekre."
        )
    else:
        macro_intro = (
            "Friss általános hírfolyam most nem áll rendelkezésre, ezért a makró blokk nem állít konkrét világhírt. "
            "A napi riport ilyenkor a portfólióban látható ármozgásra, kockázatra és ticker-szintű jelzésekre támaszkodik."
        )
    sections = {
        "macro_intro": macro_intro,
        "macro_news": macro_news[:5],
        "buy": buy_items,
        "sell": sell_items,
        "hold": hold_items,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    lines = [
        "# Napi döntéstámogató riport",
        "",
        macro_intro,
        "Ez nem pénzügyi tanácsadás, hanem adat alapú döntéstámogató nézet.",
        "",
    ]
    if macro_news:
        lines.append("## Makró és fő hírek")
        for item in macro_news[:5]:
            lines.append(f"- {item['title']} ({item.get('site') or 'hírforrás'})")
        lines.append("")
    for group in ["buy", "sell", "hold"]:
        items = [row for row in rows if row["category"] == group][:8]
        lines.append(f"## {group}")
        if not items:
            lines.append("- Nincs ticker ebben a kategóriában.")
        for item in items:
            lines.append(f"- {item['symbol']} ({item['score']:.1f}): {item['decision']} {item['reasons'][1]}")
        lines.append("")
    sections["text"] = "\n".join(lines)
    return sections


def build_state() -> dict:
    global CURRENT_STATE, CURRENT_STATE_AT
    env = load_env()
    stocks = load_portfolio()
    issues = validate_sources(env)
    symbols = [stock["symbol"] for stock in stocks]
    quotes = live_quotes(symbols, env.get("FMP_API_KEY"), issues)
    full_quotes = live_full_quotes(symbols, env.get("FMP_API_KEY"))
    histories = live_price_history(symbols, env.get("FMP_API_KEY"), issues)
    news = live_news(symbols, env.get("FMP_API_KEY"), issues)
    macro_news = live_macro_news(env.get("FMP_API_KEY"))
    calendar_events = live_calendar_events(symbols, env.get("FMP_API_KEY"))

    previous_scores: dict[str, float] = {}
    previous_state = cache_get(LATEST_STATE_CACHE, max_age_minutes=10080)
    if isinstance(previous_state, dict):
        for row in previous_state.get("rankings", []) or []:
            sym = str(row.get("symbol") or "").upper()
            if sym and row.get("score") is not None:
                try:
                    previous_scores[sym] = float(row["score"])
                except (TypeError, ValueError):
                    pass

    rows = []
    for stock in stocks:
        symbol = stock["symbol"]
        row = score_stock(
            stock,
            quotes.get(symbol),
            news.get(symbol, []),
            env,
            histories.get(symbol),
            full_quote=full_quotes.get(symbol),
            previous_score=previous_scores.get(symbol),
        )
        row["calendar_events"] = calendar_events.get(symbol, {"earnings": [], "dividends": []})
        rows.append(row)
    v2_snapshot = load_v2_snapshot()
    if v2_snapshot:
        apply_v2_overlay(rows, v2_snapshot)
    ensure_minimum_signals(rows, min_each=5)
    rows_by_action = sorted(rows, key=action_rank, reverse=True)
    rows_by_score = sorted(rows, key=lambda item: item["score"], reverse=True)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    history_real = sum(1 for row in rows if "valós napi" in str(row.get("price_source", "")))
    history_modeled = len(rows) - history_real
    state = {
        "rankings": rows_by_action,
        "score_rankings": rows_by_score,
        "actionable": [row for row in rows_by_action if row["category"] != "hold"][:12] or rows_by_action[:12],
        "market_tape": build_market_tape(rows),
        "investment_ideas": build_investment_ideas(rows, env),
        "counts": counts,
        "v2_as_of": v2_snapshot.get("as_of") if v2_snapshot else None,
        "report": build_report(rows_by_action, macro_news),
        "status": {
            "ok": not issues,
            "issues": issues,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "history_real_count": history_real,
            "history_fallback_count": history_modeled,
            "source_note": "API-kulcs előnézet nincs a dashboardon; csak hiba vagy figyelmeztetés esetén jelenik meg részlet.",
        },
    }
    cache_set(LATEST_STATE_CACHE, state)
    CURRENT_STATE = state
    CURRENT_STATE_AT = datetime.now()
    return state


def latest_state_or_build(max_age_minutes: int = 45) -> dict:
    global CURRENT_STATE, CURRENT_STATE_AT
    snap = load_v2_snapshot()
    snap_as_of = snap.get("as_of") if snap else None
    if CURRENT_STATE is not None and CURRENT_STATE_AT is not None and CURRENT_STATE.get("v2_as_of") == snap_as_of:
        if datetime.now() - CURRENT_STATE_AT <= timedelta(minutes=max_age_minutes):
            return CURRENT_STATE
    cached = cache_get(LATEST_STATE_CACHE, max_age_minutes)
    if isinstance(cached, dict) and cached.get("rankings") and cached.get("v2_as_of") == snap_as_of:
        CURRENT_STATE = cached
        CURRENT_STATE_AT = datetime.now()
        return cached
    return build_state()


def find_relevant_row(message: str, state: dict) -> dict | None:
    upper = message.upper()
    rows = state.get("rankings", [])
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol and re.search(rf"\b{re.escape(symbol)}\b", upper):
            return row
    lower = message.lower()
    for row in rows:
        name = str(row.get("name") or "").lower()
        if name and any(token in lower for token in re.findall(r"[a-zA-Z]{4,}", name)[:3]):
            return row
    return None


def compact_row_context(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "sector": row.get("sector"),
        "score": row.get("score"),
        "category": row.get("category"),
        "decision": row.get("decision"),
        "latest_price": row.get("latest_price"),
        "latest_change_pct": row.get("latest_change_pct"),
        "data_quality": row.get("data_quality"),
        "components": row.get("components"),
        "consensus_summary": row.get("consensus_summary"),
        "risks": row.get("risks"),
        "missing_data": row.get("missing_data"),
        "news": [
            {
                "title": item.get("title"),
                "site": item.get("site"),
                "published_at": item.get("published_at"),
                "url": item.get("url"),
                "interpretation": item.get("interpretation"),
            }
            for item in (row.get("news") or [])[:3]
        ],
        "calendar_events": row.get("calendar_events"),
    }


def fallback_chat_answer(message: str, state: dict, row: dict | None) -> str:
    if row:
        news_bits = "; ".join(item.get("title", "") for item in (row.get("news") or [])[:2] if item.get("title")) or "nincs friss strukturált hír"
        return (
            f"{row['symbol']} jelenlegi rendszerbesorolása: {row['category']} ({row['score']:.1f} pont). "
            f"A legfrissebb ár {row.get('latest_price'):.2f} USD, a napi változás {row.get('latest_change_pct'):+.2f}%. "
            f"A fő indok: {row.get('consensus_summary') or row.get('decision')} "
            f"Friss hírek: {news_bits}. "
            "Ez döntéstámogató összegzés, nem automatikus vételi vagy eladási utasítás."
        )
    buys = [item for item in state.get("rankings", []) if "buy" in str(item.get("category"))][:5]
    sells = [item for item in state.get("rankings", []) if "sell" in str(item.get("category"))][:5]
    buy_text = ", ".join(f"{item['symbol']} {item['score']:.0f}" for item in buys) or "nincs kiemelt buy"
    sell_text = ", ".join(f"{item['symbol']} {item['score']:.0f}" for item in sells) or "nincs kiemelt sell"
    return f"A mai kiemelt buy lista: {buy_text}. A kiemelt sell lista: {sell_text}. Kérdezz rá egy konkrét tickerre, és részletesebb, adat alapú választ adok."


def chat_answer(message: str) -> dict:
    env = load_env()
    state = build_state()
    row = find_relevant_row(message, state)
    context = {
        "question": message,
        "selected_stock": compact_row_context(row),
        "top_buy": [compact_row_context(item) for item in state.get("rankings", []) if "buy" in str(item.get("category"))][:5],
        "top_sell": [compact_row_context(item) for item in state.get("rankings", []) if "sell" in str(item.get("category"))][:5],
        "status": state.get("status"),
    }
    fallback = fallback_chat_answer(message, state, row)
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        return {"answer": fallback, "used_llm": False, "symbol": row.get("symbol") if row else None}
    payload = {
        "model": env.get("OPENAI_MODEL") or "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Te a Tőzsde AI befektetési döntéstámogató asszisztense vagy. "
                    "Csak a kapott adatsnapshotból dolgozol. Magyarul, tömören, konkrétan válaszolj. "
                    "Ne adj automatikus kereskedési utasítást; vétel/eladás helyett mindig döntéstámogató szempontokat adj."
                ),
            },
            {
                "role": "user",
                "content": "Adatsnapshot JSON:\n" + json.dumps(context, ensure_ascii=False) + "\n\nKérdés: " + message,
            },
        ],
        "temperature": 0.2,
        "max_tokens": 650,
    }
    try:
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "TozsdeAI/0.1",
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        answer = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return {"answer": answer or fallback, "used_llm": bool(answer), "symbol": row.get("symbol") if row else None}
    except Exception:
        return {"answer": fallback, "used_llm": False, "symbol": row.get("symbol") if row else None}


HTML = r"""<!doctype html>
<html lang="hu">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tzsde AI</title>
  <style>
    :root{
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      color:#111827;
      background:#f7f8fa;
      --bg:#f7f8fa;
      --surface:#ffffff;
      --surface-soft:#f1f4f7;
      --line:#dfe5ec;
      --text:#111827;
      --muted:#64748b;
      --muted2:#8794a6;
      --green:#18a957;
      --red:#d9495f;
      --blue:#2563eb;
      --amber:#b87916;
      --shadow:0 22px 60px rgba(15,23,42,.08);
    }
    *{box-sizing:border-box}
    body{margin:0;background:linear-gradient(180deg,#ffffff 0%,#f6f8fb 42%,#eef2f6 100%);color:var(--text)}
    button,input{font:inherit}
    button{border:0;cursor:pointer}
    a{color:#0f7b42;text-decoration:none}
    a:hover{text-decoration:underline}
    .screen{min-height:100vh}
    .landing{min-height:100vh;display:grid;place-items:center;padding:34px;position:relative;overflow:hidden}
    .landing:before{content:"";position:absolute;inset:-20% -10% auto;height:520px;background:radial-gradient(circle at 50% 35%,rgba(24,169,87,.13),transparent 58%);pointer-events:none}
    .landing-card{width:min(940px,100%);text-align:center;position:relative;z-index:1;animation:enter .7s ease-out both}
    .logo-hero{width:min(560px,86vw);height:auto;display:block;margin:0 auto 24px;filter:drop-shadow(0 20px 45px rgba(15,23,42,.09));animation:logoFloat 5s ease-in-out infinite}
    .intro-title{font-size:clamp(42px,6vw,76px);line-height:.96;margin:0 0 18px;letter-spacing:0;font-weight:860}
    .intro-text{font-size:22px;line-height:1.48;color:#42526a;max-width:760px;margin:0 auto 30px}
    .intro-note{font-size:17px;color:#637083;margin:0 auto 34px;max-width:760px;line-height:1.55}
    .primary-btn{display:inline-flex;align-items:center;justify-content:center;gap:10px;min-height:58px;padding:0 26px;border-radius:999px;background:#101827;color:white;font-weight:820;font-size:18px;box-shadow:0 14px 34px rgba(16,24,39,.18);transition:.18s transform,.18s box-shadow,.18s background}
    .primary-btn:hover{transform:translateY(-1px);background:#0b1220;box-shadow:0 18px 45px rgba(16,24,39,.22)}
    .primary-btn:disabled{opacity:.76;cursor:default;transform:none}
    .secondary-btn{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;background:#eef2f6;color:#111827;font-weight:760;min-height:44px;padding:0 17px}
    .loading-panel{display:none;margin:34px auto 0;width:min(680px,100%);background:rgba(255,255,255,.8);border:1px solid var(--line);border-radius:8px;padding:18px;text-align:left;box-shadow:var(--shadow);backdrop-filter:blur(18px)}
    .landing.loading .loading-panel{display:block}
    .scan-row{display:flex;align-items:center;gap:14px}
    .scan-orb{width:36px;height:36px;border-radius:999px;background:conic-gradient(from 120deg,var(--green),#b7f4cc,#e8eef4,var(--green));animation:spin 1.2s linear infinite;position:relative;flex:0 0 auto}
    .scan-orb:after{content:"";position:absolute;inset:6px;border-radius:inherit;background:white}
    .scan-title{font-size:18px;font-weight:820;margin:0 0 4px}
    .scan-stage{margin:0;color:#64748b;font-size:15px}
    .progress{height:8px;border-radius:999px;background:#e7edf3;margin-top:16px;overflow:hidden}
    .progress span{display:block;height:100%;width:36%;border-radius:inherit;background:linear-gradient(90deg,#111827,var(--green));animation:progress 2.2s ease-in-out infinite}
    .shell{display:none;min-height:100vh}
    .shell.ready{display:block}
    .topbar{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.86);backdrop-filter:blur(18px);border-bottom:1px solid rgba(223,229,236,.78)}
    .topbar-inner{max-width:1480px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;gap:22px}
    .brand-logo{width:190px;height:54px;object-fit:contain;object-position:left center;display:block}
    .top-actions{display:flex;gap:10px;align-items:center;color:#64748b;font-size:15px}
    .status-dot{width:42px;height:42px;border-radius:999px;background:#edf8f1;color:#168a49;display:grid;place-items:center;font-size:21px;position:relative}
    .status-dot.bad{background:#fff0f2;color:#c73349}
    .status-pop{display:none;position:absolute;right:0;top:50px;width:340px;background:white;border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);padding:14px;text-align:left;color:#111827;font-size:14px;line-height:1.45}
    .status-dot:hover .status-pop{display:block}
    .refresh-btn{border-radius:999px;background:#111827;color:white;min-height:42px;padding:0 16px;font-weight:780}
    .page{max-width:1480px;margin:0 auto;padding:30px 28px 56px}
    .app-intro{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(260px,.85fr);gap:34px;align-items:end;margin:10px 0 24px}
    .app-intro h1{font-size:clamp(34px,4.8vw,62px);line-height:1;margin:0 0 14px;letter-spacing:0;font-weight:860}
    .app-intro p{font-size:20px;line-height:1.5;color:#526071;margin:0;max-width:830px}
    .intro-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
    .stat{background:rgba(255,255,255,.76);border:1px solid var(--line);border-radius:8px;padding:16px}
    .stat strong{display:block;font-size:28px;color:#111827}
    .stat span{display:block;margin-top:4px;color:#64748b;font-size:14px}
    .search-wrap{position:relative;margin:22px 0 18px}
    .search-wrap input{width:100%;height:66px;border-radius:999px;border:1px solid #d9e1ea;background:#fff;padding:0 24px;font-size:21px;outline:none;box-shadow:0 12px 34px rgba(15,23,42,.06)}
    .search-wrap input:focus{border-color:#a7b4c2;box-shadow:0 16px 40px rgba(15,23,42,.09)}
    .filter-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:22px}
    .filter-btn{background:transparent;color:#566474;font-weight:780;font-size:16px;padding:9px 2px;border-bottom:2px solid transparent;margin-right:18px}
    .filter-btn.active{color:#111827;border-bottom-color:#111827}
    .workspace{display:grid;grid-template-columns:minmax(420px,520px) minmax(0,1fr);gap:24px;align-items:start}
    .list-panel,.detail-panel{background:rgba(255,255,255,.82);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow)}
    .list-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:18px 18px 10px}
    .list-head h2{font-size:24px;margin:0}
    .list-head span{color:#64748b;font-size:15px}
    .stock-list{display:grid;gap:0;max-height:calc(100vh - 280px);overflow:auto;padding:0 8px 8px}
    .stock-row{display:grid;grid-template-columns:70px minmax(0,1fr) 74px;gap:14px;align-items:center;border-radius:8px;padding:16px 10px;background:transparent;color:inherit;text-align:left;width:100%;border-bottom:1px solid #edf1f5}
    .stock-row:hover,.stock-row.active{background:#f3f6f9}
    .stock-symbol{font-size:22px;font-weight:860}
    .stock-name{font-size:16px;font-weight:730;margin:0 0 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .stock-meta{font-size:14px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .score-pill{justify-self:end;border-radius:999px;background:#f0f3f6;color:#111827;font-size:17px;font-weight:860;padding:8px 10px;min-width:58px;text-align:center}
    .label{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 10px;font-size:13px;font-weight:860;text-transform:lowercase;background:#eef2f6;color:#334155}
    .label.strong-buy,.label.buy{background:#eaf8ef;color:#0f7b42}
    .label.strong-sell,.label.sell{background:#fff0f2;color:#b42338}
    .label.hold{background:#eef5ff;color:#2457a6}
    .detail-panel{min-height:560px;padding:26px;position:sticky;top:92px}
    .empty-detail{min-height:480px;display:grid;place-items:center;text-align:center;color:#64748b;padding:40px}
    .empty-detail h2{font-size:30px;color:#111827;margin:0 0 10px}
    .detail-head{display:flex;justify-content:space-between;gap:24px;align-items:start;border-bottom:1px solid #edf1f5;padding-bottom:20px;margin-bottom:22px}
    .detail-head h2{font-size:46px;line-height:1;margin:0 0 8px}
    .detail-head p{font-size:18px;color:#5b6878;margin:0}
    .decision-box{display:grid;gap:8px;text-align:right;min-width:180px}
    .decision-box strong{font-size:34px;line-height:1;color:#111827}
    .decision-box span{font-size:15px;color:#64748b}
    .price-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 24px}
    .price-cell{background:#f6f8fa;border:1px solid #e8edf2;border-radius:8px;padding:14px}
    .price-cell span{display:block;color:#64748b;font-size:14px;margin-bottom:5px}
    .price-cell strong{display:block;color:#111827;font-size:26px;line-height:1.1}
    .section{border-top:1px solid #edf1f5;padding-top:22px;margin-top:22px}
    .section:first-of-type{border-top:0;padding-top:0}
    .section h3{font-size:24px;margin:0 0 12px}
    .consensus{font-size:20px;line-height:1.5;color:#303b49;margin:0}
    .agent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .agent-card{border:1px solid #e5ebf1;background:#fff;border-radius:8px;padding:16px}
    .agent-card header{display:flex;justify-content:space-between;gap:12px;align-items:start;margin-bottom:9px}
    .agent-card b{font-size:17px}
    .agent-card .agent-score{font-weight:850;color:#111827}
    .agent-card p{margin:0;color:#4c5969;line-height:1.46;font-size:16px}
    .news-list{display:grid;gap:12px}
    .news-item{border:1px solid #e5ebf1;background:#fff;border-radius:8px;padding:16px}
    .news-title{font-size:18px;font-weight:820;line-height:1.3;margin:0 0 7px;display:block;color:#111827}
    .news-item p{font-size:16px;line-height:1.5;color:#4c5969;margin:0 0 10px}
    .news-source{display:flex;gap:8px;flex-wrap:wrap;color:#64748b;font-size:13px}
    .source-badge{border-radius:999px;padding:4px 8px;background:#eef2f6;color:#334155;font-weight:760}
    .source-primary{background:#eaf8ef;color:#0f7b42}.source-established{background:#eef5ff;color:#2457a6}.source-opinion{background:#fff7e8;color:#92610d}
    .event-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .event-card{border:1px solid #e5ebf1;background:#fff;border-radius:8px;padding:16px}
    .event-card b{display:block;font-size:17px;margin-bottom:5px}.event-card span{color:#64748b;font-size:15px;display:block;line-height:1.45}
    .method-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
    .method-cell{background:#f6f8fa;border:1px solid #e8edf2;border-radius:8px;padding:12px}
    .method-cell span{display:block;color:#64748b;font-size:13px}.method-cell strong{font-size:22px;color:#111827}
    .chart{height:118px;display:flex;align-items:end;gap:2px;border-bottom:1px solid #dfe5ec;padding-top:10px}
    .bar{flex:1 1 0;min-width:2px;border-radius:3px 3px 0 0;background:#9aa8b8;position:relative}
    .bar.up{background:linear-gradient(180deg,#38c46f,#168a49)}.bar.down{background:linear-gradient(180deg,#e75d70,#c73349)}.bar.flat{background:#94a3b8}
    .bar:hover:after{content:attr(data-tip);position:absolute;left:50%;bottom:calc(100% + 8px);transform:translateX(-50%);white-space:nowrap;background:#111827;color:white;border-radius:8px;padding:7px 9px;font-size:13px;font-weight:760;z-index:5;box-shadow:0 10px 28px rgba(15,23,42,.2)}
    .chart-caption{display:flex;justify-content:space-between;color:#64748b;font-size:14px;margin-top:8px}
    .warning{border:1px solid #f0c7ce;background:#fff6f7;border-radius:8px;padding:12px;color:#8f1f31;margin-top:14px}
    .small{font-size:14px;color:#64748b;line-height:1.45}
    @keyframes enter{from{opacity:0;transform:translateY(18px) scale(.985)}to{opacity:1;transform:none}}
    @keyframes logoFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
    @keyframes spin{to{transform:rotate(360deg)}}
    @keyframes progress{0%{transform:translateX(-80%);width:32%}50%{width:68%}100%{transform:translateX(310%);width:32%}}
    @media(max-width:1100px){.workspace,.app-intro{grid-template-columns:1fr}.detail-panel{position:static}.stock-list{max-height:none}.price-grid,.method-grid,.agent-grid,.event-grid,.intro-stats{grid-template-columns:1fr 1fr}}
    @media(max-width:720px){.landing{padding:24px 18px}.intro-title{font-size:42px}.intro-text{font-size:19px}.topbar-inner,.page{padding-left:18px;padding-right:18px}.brand-logo{width:150px}.top-actions .checked{display:none}.price-grid,.method-grid,.agent-grid,.event-grid,.intro-stats{grid-template-columns:1fr}.detail-head{display:block}.decision-box{text-align:left;margin-top:18px}.stock-row{grid-template-columns:58px minmax(0,1fr) 58px}}
  </style>
</head>
<body>
  <section id="landing" class="screen landing">
    <div class="landing-card">
      <img class="logo-hero" src="/brand/logo.png" alt="Tzsde AI" />
      <h1 class="intro-title">Befektetsi kutats, tisztn.</h1>
      <p class="intro-text">A Tzsde AI nem kereskedik helyetted. sszegyjti a friss rakat, hreket, naptri esemnyeket s agent-vlemnyeket, hogy gyorsabban rtsd meg, mi mozgatja a figyelt cgeket.</p>
      <p class="intro-note">A rendszer a 100 tickeres listt vizsglja. A trtneti rfolyamokat cache-ben tartja, ezrt norml hasznlatnl csak a hinyzvagy friss adatokrt nyl ki jra.</p>
      <button id="startBtn" class="primary-btn" type="button">Kutats indtsa</button>
      <div class="loading-panel" aria-live="polite">
        <div class="scan-row">
          <div class="scan-orb"></div>
          <div>
            <p class="scan-title">Friss kutats fut</p>
            <p id="stageText" class="scan-stage">rfolyamok s cache ellenrzse...</p>
          </div>
        </div>
        <div class="progress"><span></span></div>
      </div>
    </div>
  </section>

  <section id="shell" class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <img class="brand-logo" src="/brand/logo.png" alt="Tzsde AI" />
        <div class="top-actions">
          <span id="checkedAt" class="checked">Nincs friss adat</span>
          <button id="refreshBtn" class="refresh-btn" type="button">j kutats</button>
          <div id="statusDot" class="status-dot" role="button" tabindex="0"><div id="statusPop" class="status-pop"></div></div>
        </div>
      </div>
    </header>

    <main class="page">
      <section class="app-intro">
        <div>
          <h1>Rszvnykutats</h1>
          <p>Egyszerlista, rszletes magyarzat. Kattints egy paprra, s alatta azonnal ltod az agentek vlemnyt, a konkrt hreket, a kvetkezesemnyeket s a pontozs bontst.</p>
        </div>
        <div class="intro-stats">
          <div class="stat"><strong id="statTickers">0</strong><span>ticker figyelve</span></div>
          <div class="stat"><strong id="statReal">0</strong><span>vals napi idsor</span></div>
          <div class="stat"><strong id="statSignals">0</strong><span>akcis jelzs</span></div>
        </div>
      </section>

      <div class="search-wrap">
        <input id="searchInput" type="search" placeholder="Keress tickerre, cgre vagy szektorra" />
      </div>

      <div class="filter-row" id="filters">
        <button class="filter-btn active" data-filter="priority" type="button">Kiemelt</button>
        <button class="filter-btn" data-filter="buy" type="button">Buy</button>
        <button class="filter-btn" data-filter="sell" type="button">Sell</button>
        <button class="filter-btn" data-filter="hold" type="button">Watch</button>
        <button class="filter-btn" data-filter="all" type="button">Minden</button>
      </div>

      <section class="workspace">
        <aside class="list-panel">
          <div class="list-head">
            <h2>Figyelt paprok</h2>
            <span id="listCount">0 tallat</span>
          </div>
          <div id="stockList" class="stock-list"></div>
        </aside>
        <section id="detailPanel" class="detail-panel">
          <div class="empty-detail">
            <div>
              <h2>Vlassz egy rszvnyt.</h2>
              <p>Az elemzs itt nylik meg, nem az oldal aljn.</p>
            </div>
          </div>
        </section>
      </section>
    </main>
  </section>

  <script>
    let state = null;
    let selectedSymbol = null;
    let filter = "priority";
    const stages = [
      "rfolyamok s cache ellenrzse...",
      "Friss hrek megbzhatsgi szrse...",
      "Osztalk s jelentsi naptr lekrse...",
      "Agent-vlemnyek sszelltsa...",
      "Konszenzus s rangsor ksztse..."
    ];
    let stageTimer = null;

    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value "").replace(/[&<>"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[ch]));
    const fmt = (value, digits=2) => Number.isFinite(Number(value)) Number(value).toLocaleString("hu-HU", {minimumFractionDigits:digits, maximumFractionDigits:digits}) : "nincs adat";
    const pct = (value) => Number.isFinite(Number(value)) `${Number(value) >= 0 "+" : ""}${fmt(value,2)}%` : "nincs adat";
    const catText = (cat) => ({"strong buy":"strong buy", buy:"buy", hold:"hold", sell:"sell", "strong sell":"strong sell"}[cat] || cat || "nincs adat");
    const catIcon = (cat) => cat === "hold" "" : (String(cat).includes("buy") "" : "");

    function sourceText(n){
      const pieces = [];
      if(n.site) pieces.push(n.site);
      if(n.published_at) pieces.push(n.published_at);
      return pieces.join(" ") || "forrs nincs megadva";
    }

    function beginStageLoop(){
      let idx = 0;
      $("stageText").textContent = stages[0];
      clearInterval(stageTimer);
      stageTimer = setInterval(() => {
        idx = (idx + 1) % stages.length;
        $("stageText").textContent = stages[idx];
      }, 1450);
    }

    async function startResearch(){
      const landing = $("landing");
      const startBtn = $("startBtn");
      landing.classList.add("loading");
      startBtn.disabled = true;
      startBtn.textContent = "Kutats fut";
      beginStageLoop();
      try{
        const response = await fetch("/api/refresh", {method:"POST"});
        if(!response.ok) throw new Error("A helyi szerver nem adott vlaszt.");
        state = await response.json();
        clearInterval(stageTimer);
        selectedSymbol = null;
        renderApp();
        landing.style.display = "none";
        $("shell").classList.add("ready");
      }catch(error){
        clearInterval(stageTimer);
        $("stageText").textContent = `Hiba trtnt: ${error.message}`;
        startBtn.disabled = false;
        startBtn.textContent = "jraprblom";
      }
    }

    function visibleRows(){
      if(!state) return [];
      const q = $("searchInput").value.trim().toLowerCase();
      return state.rankings.filter(row => {
        const cat = row.category || "";
        const filterOk = filter === "all" ||
          (filter === "priority" && cat !== "hold") ||
          (filter === "buy" && cat.includes("buy")) ||
          (filter === "sell" && cat.includes("sell")) ||
          (filter === "hold" && cat === "hold");
        const text = `${row.symbol} ${row.name} ${row.sector}`.toLowerCase();
        return filterOk && (!q || text.includes(q));
      });
    }

    function renderApp(){
      const rows = state.rankings || [];
      const actionable = rows.filter(row => row.category !== "hold").length;
      $("checkedAt").textContent = state.status.checked_at `Frisstve: ${state.status.checked_at}` : "Frisstve";
      $("statTickers").textContent = rows.length;
      $("statReal").textContent = state.status.history_real_count 0;
      $("statSignals").textContent = actionable;
      renderStatus();
      renderList();
      renderDetail();
    }

    function renderStatus(){
      const status = state.status || {};
      const issues = status.issues || [];
      const dot = $("statusDot");
      dot.classList.toggle("bad", issues.length > 0);
      dot.firstChild.nodeValue = issues.length "!" : "";
      $("statusPop").innerHTML = issues.length 
        `<strong>Rendszerjelzs</strong>${issues.map(issue => `<div class="warning"><b>${esc(issue.source || "Rendszer")}: ${esc(issue.title || "Figyelmeztets")}</b><br>${esc(issue.detail || "")}</div>`).join("")}` :
        `<strong>Minden rendben.</strong><p class="small">A kulcsokat nem jelentjk meg. Vals napi idsor: ${esc(status.history_real_count 0)}. Fallback idsor: ${esc(status.history_fallback_count 0)}.</p>`;
    }

    function renderList(){
      const rows = visibleRows();
      $("listCount").textContent = `${rows.length} tallat`;
      $("stockList").innerHTML = rows.map(row => `
        <button class="stock-row ${row.symbol === selectedSymbol "active" : ""}" type="button" data-symbol="${esc(row.symbol)}">
          <div class="stock-symbol">${esc(row.symbol)}</div>
          <div>
            <p class="stock-name">${esc(row.name)}</p>
            <div class="stock-meta"><span class="label ${esc(row.category_class)}">${catIcon(row.category)} ${catText(row.category)}</span> ${esc(row.sector || "szektor nincs megadva")}</div>
          </div>
          <div class="score-pill">${fmt(row.score,0)}</div>
        </button>
      `).join("") || `<div class="empty-detail"><p>Nincs tallat erre a keressre.</p></div>`;
      document.querySelectorAll(".stock-row").forEach(btn => btn.addEventListener("click", () => {
        const symbol = btn.dataset.symbol;
        selectedSymbol = selectedSymbol === symbol null : symbol;
        renderList();
        renderDetail();
      }));
    }

    function selectedRow(){
      if(!state || !selectedSymbol) return null;
      return state.rankings.find(row => row.symbol === selectedSymbol) || null;
    }

    function renderDetail(){
      const row = selectedRow();
      if(!row){
        $("detailPanel").innerHTML = `<div class="empty-detail"><div><h2>Vlassz egy rszvnyt.</h2><p>Az elemzs itt nylik meg, nem az oldal aljn.</p></div></div>`;
        return;
      }
      const changeText = `${fmt(row.latest_change,2)} USD ${pct(row.latest_change_pct)}`;
      $("detailPanel").innerHTML = `
        <div class="detail-head">
          <div>
            <h2>${esc(row.symbol)}</h2>
            <p>${esc(row.name)} ${esc(row.sector || "szektor nincs megadva")}</p>
          </div>
          <div class="decision-box">
            <span class="label ${esc(row.category_class)}">${catIcon(row.category)} ${catText(row.category)}</span>
            <strong>${fmt(row.score,1)}</strong>
            <span>pontszm meggyzds ${fmt(row.conviction,1)}</span>
          </div>
        </div>
        <div class="price-grid">
          <div class="price-cell"><span>Aktulis r</span><strong>${fmt(row.latest_price,2)} USD</strong></div>
          <div class="price-cell"><span>Napi vltozs</span><strong>${changeText}</strong></div>
          <div class="price-cell"><span>Volumen</span><strong>${row.latest_volume Number(row.latest_volume).toLocaleString("hu-HU") : "nincs adat"}</strong></div>
          <div class="price-cell"><span>Adatbizalom</span><strong>${fmt(row.data_quality,0)}/100</strong></div>
        </div>
        <section class="section">
          <h3>Agent konszenzus</h3>
          <p class="consensus">${esc(row.consensus_summary || row.decision)}</p>
        </section>
        <section class="section">
          <h3>Agent-vlemnyek</h3>
          <div class="agent-grid">${renderAgents(row)}</div>
        </section>
        <section class="section">
          <h3>Friss hrek</h3>
          <div class="news-list">${renderNews(row)}</div>
        </section>
        <section class="section">
          <h3>Kvetkezesemnyek</h3>
          <div class="event-grid">${renderEvents(row)}</div>
        </section>
        <section class="section">
          <h3>Pontozsi bonts</h3>
          <div class="method-grid">${renderComponents(row)}</div>
          <p class="small">A pontszm dntstmogatrangsor. Nem automatikus vteli vagy eladsi utasts.</p>
        </section>
        <section class="section">
          <h3>rfolyam httr</h3>
          ${renderChart(row)}
          <p class="small">Forrs: ${esc(row.price_source || "nincs forrs")}. A chart httradat, a fnzet az informcis s agent-kutats.</p>
        </section>
      `;
    }

    function renderAgents(row){
      return (row.agent_debate || []).map(agent => `
        <article class="agent-card">
          <header><b>${esc(agent.agent)}</b><span class="agent-score">${fmt(agent.score,0)}</span></header>
          <p>${esc(agent.thesis)}</p>
        </article>
      `).join("") || `<p class="small">Nincs agent-vlemny.</p>`;
    }

    function renderNews(row){
      const items = row.news || [];
      if(!items.length) return `<p class="small">Ehhez a tickerhez most nincs friss, strukturlt hr. Ilyenkor a rendszer ezt jelzi, nem tall ki trtnetet.</p>`;
      return items.map(n => {
        const title = esc(n.title || "Cm nlkli hr");
        const linked = n.url `<a class="news-title" href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : `<span class="news-title">${title}</span>`;
        const body = n.interpretation || n.text || "A hrhez nincs kln sszefoglal.";
        const sourceClass = n.source_class || "";
        return `<article class="news-item">${linked}<p>${esc(body)}</p><div class="news-source"><span class="source-badge ${esc(sourceClass)}">${esc(n.source_label || "forrs")}</span><span>${esc(sourceText(n))}</span></div></article>`;
      }).join("");
    }

    function renderEvents(row){
      const events = row.calendar_events || {earnings:[], dividends:[]};
      const earnings = (events.earnings || [])[0];
      const dividend = (events.dividends || [])[0];
      const earningsHtml = earnings `<div class="event-card"><b>${esc(earnings.title || "Eredmnyjelents")}</b><span>Dtum: ${esc(earnings.date || "nincs adat")}</span><span>EPS becsls: ${esc(earnings.eps_estimated "nincs adat")}</span><span>Bevtel becsls: ${esc(earnings.revenue_estimated "nincs adat")}</span></div>` : `<div class="event-card"><b>Eredmnyjelents</b><span>Nincs lekrt naptri dtum ehhez a tickerhez.</span></div>`;
      const dividendHtml = dividend `<div class="event-card"><b>${esc(dividend.title || "Osztalk")}</b><span>Dtum: ${esc(dividend.date || "nincs adat")}</span><span>Osztalk: ${esc(dividend.dividend "nincs adat")}</span><span>Fizetsi nap: ${esc(dividend.payment_date || "nincs adat")}</span></div>` : `<div class="event-card"><b>Osztalk</b><span>Nincs lekrt osztalkesemny a kvetkez120 napra.</span></div>`;
      return earningsHtml + dividendHtml;
    }

    function renderComponents(row){
      const labels = {momentum:"Momentum", fundamentals:"Fundamentum", valuation:"rtkeltsg", events:"Esemny", risk:"Kockzat"};
      return Object.entries(labels).map(([key,label]) => `<div class="method-cell"><span>${label}</span><strong>${fmt(row.components.[key],0)}</strong></div>`).join("");
    }

    function renderChart(row){
      const prices = (row.prices || []).slice(-64);
      if(prices.length < 3) return `<p class="small">Nincs elg rfolyamadat chart ksztshez.</p>`;
      const closes = prices.map(p => Number(p.close)).filter(Number.isFinite);
      const min = Math.min(...closes);
      const max = Math.max(...closes);
      const bars = prices.map((p, idx) => {
        const close = Number(p.close);
        const prev = idx > 0 Number(prices[idx - 1].close) : close;
        const h = max === min 45 : 12 + ((close - min) / (max - min)) * 88;
        const klass = close > prev "up" : close < prev "down" : "flat";
        return `<div class="bar ${klass}" style="height:${h}%" data-tip="${esc(p.date)} ${fmt(close,2)} USD"></div>`;
      }).join("");
      return `<div class="chart">${bars}</div><div class="chart-caption"><span>${esc(prices[0].date)}</span><span>${esc(prices[prices.length - 1].date)}</span></div>`;
    }

    $("startBtn").addEventListener("click", startResearch);
    $("refreshBtn").addEventListener("click", async () => {
      $("refreshBtn").textContent = "Frissts...";
      $("refreshBtn").disabled = true;
      try{
        const response = await fetch("/api/refresh", {method:"POST"});
        state = await response.json();
        renderApp();
      }finally{
        $("refreshBtn").textContent = "j kutats";
        $("refreshBtn").disabled = false;
      }
    });
    $("searchInput").addEventListener("input", renderList);
    document.querySelectorAll(".filter-btn").forEach(btn => btn.addEventListener("click", () => {
      filter = btn.dataset.filter;
      document.querySelectorAll(".filter-btn").forEach(item => item.classList.toggle("active", item === btn));
      renderList();
    }));
  </script>
</body>
</html>"""

# ===== Shadow Portfolio (paper trading) =====
SHADOW_CACHE_KEY = "shadow_portfolio_v1"
SHADOW_STARTING_BALANCE = 10000.0
SHADOW_DAILY_BUDGET = 1500.0
SHADOW_MAX_POSITIONS = 12
SHADOW_LONG_DEFAULT_TARGET_PCT = 0.20   # 20% upside target if system has no specific target
SHADOW_LONG_STOP_PCT = -0.10            # 10% stop loss on longs
SHADOW_SHORT_TARGET_PCT = -0.15         # short profits when price drops 15%
SHADOW_SHORT_STOP_PCT = 0.08            # short stops out when price rises 8%
SHADOW_LONGS_PER_CYCLE = 2
SHADOW_SHORTS_PER_CYCLE = 1


def shadow_init_portfolio() -> dict:
    return {
        "cash": SHADOW_STARTING_BALANCE,
        "starting_balance": SHADOW_STARTING_BALANCE,
        "positions": [],
        "closed_trades": [],
        "events": [],
        "created_at": datetime.now().isoformat(),
        "last_traded_at": None,
        "trade_count": 0,
    }


def shadow_load() -> dict:
    cached = cache_get(SHADOW_CACHE_KEY, 60 * 24 * 30)  # 30 days max age
    if isinstance(cached, dict) and "cash" in cached and isinstance(cached.get("positions"), list):
        cached.setdefault("events", [])
        cached.setdefault("closed_trades", [])
        return cached
    return shadow_init_portfolio()


def shadow_save(state: dict) -> None:
    cache_set(SHADOW_CACHE_KEY, state)


def shadow_mark_to_market(state: dict, price_map: dict) -> dict:
    """Update unrealized P&L and total portfolio value using current prices."""
    long_value = 0.0
    short_unrealized = 0.0
    for pos in state["positions"]:
        sym = pos["symbol"]
        current = float(price_map.get(sym) or pos["entry_price"])
        pos["current_price"] = round(current, 2)
        if pos["direction"] == "long":
            pos["unrealized_pnl"] = round((current - pos["entry_price"]) * pos["shares"], 2)
            pos["unrealized_pct"] = round((current / pos["entry_price"] - 1) * 100, 2)
            long_value += pos["shares"] * current
        else:
            # Short: P&L = (entry - current) * shares; collateral (cost) is held in margin
            pnl = (pos["entry_price"] - current) * pos["shares"]
            pos["unrealized_pnl"] = round(pnl, 2)
            pos["unrealized_pct"] = round((pos["entry_price"] / current - 1) * 100, 2) if current > 0 else 0.0
            short_unrealized += pnl
            long_value += pos["shares"] * pos["entry_price"]  # collateral counted at entry value

    realized = sum(t.get("realized_pnl", 0) for t in state.get("closed_trades", []))
    total_value = state["cash"] + long_value + short_unrealized
    state["invested_value"] = round(long_value, 2)
    state["realized_pnl"] = round(realized, 2)
    state["unrealized_pnl"] = round(sum(p.get("unrealized_pnl", 0) for p in state["positions"]), 2)
    state["total_value"] = round(total_value, 2)
    state["total_pnl"] = round(state["realized_pnl"] + state["unrealized_pnl"], 2)
    base = state.get("starting_balance") or SHADOW_STARTING_BALANCE
    state["total_pnl_pct"] = round((total_value / base - 1) * 100, 2)
    return state


def shadow_run_cycle(state: dict, rankings: list[dict]) -> dict:
    """Execute one trading cycle. Modifies state in-place and returns it.

    Logic:
      1. Mark-to-market all positions.
      2. Close positions that hit their target (profit), stop (loss), or had their signal flip.
      3. With remaining cash budget, open up to N new long positions (top BUY-rated)
         and M new short positions (worst SELL-rated) not already held.
      4. No commissions, no slippage. Position sizing = equal share of today's budget.
    """
    events_log = state.setdefault("events", [])
    price_map = {r["symbol"]: float(r.get("latest_price") or 0) for r in rankings if r.get("latest_price")}
    cat_map = {r["symbol"]: (r.get("category") or "hold") for r in rankings}
    score_map = {r["symbol"]: float(r.get("score") or 50) for r in rankings}

    cycle_ts = datetime.now().isoformat()

    # Step 1: close positions that hit conditions
    remaining = []
    for pos in state["positions"]:
        sym = pos["symbol"]
        current = float(price_map.get(sym) or pos["entry_price"])
        current_cat = cat_map.get(sym, "hold")

        should_close = False
        reason = ""
        if pos["direction"] == "long":
            if current >= pos["target_price"]:
                should_close, reason = True, "célár elérve"
            elif current <= pos["stop_price"]:
                should_close, reason = True, "stop loss"
            elif current_cat == "sell":
                should_close, reason = True, "jelzés átfordult sell-re"
        else:
            if current <= pos["target_price"]:
                should_close, reason = True, "short célár elérve (ár leesett)"
            elif current >= pos["stop_price"]:
                should_close, reason = True, "short stop (ár felment)"
            elif current_cat == "buy":
                should_close, reason = True, "jelzés átfordult buy-ra"

        if should_close:
            if pos["direction"] == "long":
                proceeds = pos["shares"] * current
                realized = (current - pos["entry_price"]) * pos["shares"]
                state["cash"] += proceeds
            else:
                # Short: return collateral + P&L
                realized = (pos["entry_price"] - current) * pos["shares"]
                state["cash"] += pos["cost"] + realized
            closed = {
                **pos,
                "exit_price": round(current, 2),
                "exit_at": cycle_ts,
                "realized_pnl": round(realized, 2),
                "realized_pct": round(realized / pos["cost"] * 100, 2) if pos.get("cost") else 0.0,
                "close_reason": reason,
            }
            state["closed_trades"].append(closed)
            events_log.append({
                "at": cycle_ts, "type": "close", "symbol": pos["symbol"],
                "direction": pos["direction"], "shares": pos["shares"],
                "price": round(current, 2), "pnl": closed["realized_pnl"],
                "pnl_pct": closed["realized_pct"], "reason": reason,
            })
        else:
            remaining.append(pos)
    state["positions"] = remaining

    # Step 2: open new positions
    if len(state["positions"]) >= SHADOW_MAX_POSITIONS:
        events_log.append({"at": cycle_ts, "type": "skip", "reason": f"max {SHADOW_MAX_POSITIONS} pozíció elérve"})
    else:
        budget = min(SHADOW_DAILY_BUDGET, max(0.0, state["cash"] * 0.20))
        held = {p["symbol"] for p in state["positions"]}
        buy_candidates = sorted(
            [r for r in rankings if cat_map.get(r["symbol"]) == "buy" and r["symbol"] not in held and price_map.get(r["symbol"], 0) > 0],
            key=lambda r: -score_map.get(r["symbol"], 50),
        )
        sell_candidates = sorted(
            [r for r in rankings if cat_map.get(r["symbol"]) == "sell" and r["symbol"] not in held and price_map.get(r["symbol"], 0) > 0],
            key=lambda r: score_map.get(r["symbol"], 50),
        )
        picks = [("long", c) for c in buy_candidates[:SHADOW_LONGS_PER_CYCLE]] + \
                [("short", c) for c in sell_candidates[:SHADOW_SHORTS_PER_CYCLE]]
        slots_available = max(0, SHADOW_MAX_POSITIONS - len(state["positions"]))
        picks = picks[:slots_available]

        if not picks:
            events_log.append({"at": cycle_ts, "type": "skip", "reason": "nincs érvényes jelzés"})
        elif budget < 100:
            events_log.append({"at": cycle_ts, "type": "skip", "reason": "nincs elég készpénz"})
        else:
            per_pos_budget = budget / len(picks)
            for direction, row in picks:
                price = float(price_map.get(row["symbol"]) or 0)
                if price <= 0:
                    continue
                shares = int(per_pos_budget // price)
                if shares < 1:
                    continue
                cost = shares * price
                if cost > state["cash"]:
                    continue
                if direction == "long":
                    sys_target = row.get("target_price")
                    target = float(sys_target) if sys_target and float(sys_target) > price else price * (1 + SHADOW_LONG_DEFAULT_TARGET_PCT)
                    stop = price * (1 + SHADOW_LONG_STOP_PCT)
                else:
                    target = price * (1 + SHADOW_SHORT_TARGET_PCT)
                    stop = price * (1 + SHADOW_SHORT_STOP_PCT)
                state["cash"] -= cost
                pos = {
                    "symbol": row["symbol"],
                    "name": row.get("name"),
                    "direction": direction,
                    "shares": shares,
                    "entry_price": round(price, 2),
                    "entry_at": cycle_ts,
                    "target_price": round(target, 2),
                    "stop_price": round(stop, 2),
                    "cost": round(cost, 2),
                    "category_at_entry": row.get("category"),
                    "score_at_entry": score_map.get(row["symbol"]),
                }
                state["positions"].append(pos)
                events_log.append({
                    "at": cycle_ts, "type": "open", "symbol": row["symbol"],
                    "direction": direction, "shares": shares, "price": round(price, 2),
                    "cost": round(cost, 2), "target": round(target, 2), "stop": round(stop, 2),
                    "score": score_map.get(row["symbol"]),
                })
                state["trade_count"] += 1

    # Trim events log to last 50 to keep cache size manageable
    state["events"] = events_log[-50:]
    state["last_traded_at"] = cycle_ts
    shadow_mark_to_market(state, price_map)
    return state


def shadow_get_state(execute_cycle: bool = False) -> dict:
    """Returns the shadow portfolio state, optionally executing a trading cycle first."""
    market_state = latest_state_or_build()
    rankings = market_state.get("rankings", [])
    state = shadow_load()
    if execute_cycle:
        state = shadow_run_cycle(state, rankings)
        shadow_save(state)
    else:
        price_map = {r["symbol"]: float(r.get("latest_price") or 0) for r in rankings if r.get("latest_price")}
        if price_map:
            shadow_mark_to_market(state, price_map)
    return state


def shadow_reset() -> dict:
    """Reset the shadow portfolio back to starting balance."""
    state = shadow_init_portfolio()
    shadow_save(state)
    return state


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self.send_json(latest_state_or_build())
            return
        if path == "/api/shadow":
            v2_shadow = load_v2_shadow()
            if v2_shadow:
                self.send_json(v2_shadow)
                return
            self.send_json(shadow_get_state(execute_cycle=False))
            return
        if path.startswith("/api/analyst-targets/"):
            symbol = path.rsplit("/", 1)[-1].upper()
            env = load_env()
            self.send_json(fetch_analyst_target(symbol, env.get("FMP_API_KEY")))
            return
        if path == "/brand/logo.png" and LOGO_PATH.exists():
            body = LOGO_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/brand/logo-hero.png" and LOGO_HERO_PATH.exists():
            body = LOGO_HERO_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/brand/favicon") or path == "/favicon.ico":
            filename = path.rsplit("/", 1)[-1]
            if filename == "favicon.ico" and path == "/favicon.ico":
                filename = "favicon.ico"
            asset_path = ROOT / "brand" / filename
            if asset_path.exists() and asset_path.suffix.lower() in {".png", ".ico"} and ".." not in filename:
                body = asset_path.read_bytes()
                ctype = "image/png" if asset_path.suffix.lower() == ".png" else "image/x-icon"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=604800")
                self.end_headers()
                self.wfile.write(body)
                return
        if FRONTEND_PATH.exists():
            body = FRONTEND_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/api/refresh":
            self.send_json(latest_state_or_build(20))
            return
        if urlparse(self.path).path == "/api/shadow/trade":
            self.send_json(shadow_get_state(execute_cycle=True))
            return
        if urlparse(self.path).path == "/api/shadow/reset":
            self.send_json(shadow_reset())
            return
        if urlparse(self.path).path == "/api/chat":
            try:
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(body)
                message = str(payload.get("message") or "").strip()
            except Exception:
                message = ""
            if not message:
                self.send_json({"answer": "Írj be egy konkrét kérdést, például: mi a helyzet Apple-lel?", "used_llm": False})
                return
            self.send_json(chat_answer(message))
            return
        self.send_response(404)
        self.end_headers()

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Tőzsde AI preview: http://127.0.0.1:{PORT}")
    server.serve_forever()
