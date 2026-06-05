from dataclasses import dataclass
from datetime import date, timedelta
import json
import statistics


SECTOR_PE_BASELINE: dict[str, float] = {
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


def _sector_pe_baseline(sector: str | None) -> float:
    if not sector:
        return 22.0
    if sector in SECTOR_PE_BASELINE:
        return SECTOR_PE_BASELINE[sector]
    lower = sector.lower()
    for key, value in SECTOR_PE_BASELINE.items():
        if key.lower() in lower:
            return float(value)
    return 22.0


def _safe_float(value) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        v = float(str(value).replace("%", "").replace(",", ""))
        import math
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


@dataclass
class ScoreResult:
    score: float
    category: str
    components: dict[str, float]
    reasons: list[str]
    risks: list[str]
    missing_data: list[str]
    snapshot: dict


def score_stock(
    symbol: str,
    prices: list[dict],
    filings: list[dict],
    target: dict | None,
    target_status: str,
    sector: str | None = None,
    full_quote: dict | None = None,
) -> ScoreResult:
    missing_data: list[str] = []
    if not prices:
        missing_data.append("Nincs árfolyam idősor.")
    if target_status != "fmp":
        missing_data.append("Nincs friss célár/elemzői konszenzus adat.")
    if not filings:
        missing_data.append("Nincs friss SEC filing adat vagy hiányzik a CIK.")

    closes = [float(p["close"]) for p in prices]
    latest = closes[-1] if closes else 0.0
    momentum = _momentum_score(closes)
    fundamentals, fund_notes = _fundamentals_score(closes, full_quote, sector)
    valuation = _valuation_score(latest, target)
    events = _events_score(filings)
    risk = _risk_score(closes)

    weighted = momentum * 0.25 + fundamentals * 0.25 + valuation * 0.20 + events * 0.15 + risk * 0.15
    base_score = round(max(0.0, min(100.0, weighted)), 1)
    agents = _agent_debate(symbol, momentum, fundamentals, valuation, events, risk, missing_data)
    agent_score = statistics.fmean(agent["score"] for agent in agents)
    score = round(max(0.0, min(100.0, base_score * 0.65 + agent_score * 0.35)), 1)
    category = category_for_score(score)

    reasons = _reasons(symbol, closes, latest, target, filings, momentum, fundamentals, valuation, events, fund_notes)
    reasons.insert(0, f"Multi-agent konszenzus: {category}, konszenzuspont: {score:.1f}.")
    risks = _risks(closes, target_status, filings, full_quote)
    snapshot = {
        "symbol": symbol,
        "latest_price": latest,
        "base_score": base_score,
        "consensus_score": score,
        "price_points": len(prices),
        "target": target,
        "target_status": target_status,
        "recent_filings": filings[:5],
        "components": {
            "momentum": round(momentum, 1),
            "fundamentals": round(fundamentals, 1),
            "valuation": round(valuation, 1),
            "events": round(events, 1),
            "risk": round(risk, 1),
        },
        "agent_debate": agents,
        "missing_data": missing_data,
        "fundamentals_notes": fund_notes,
    }
    return ScoreResult(
        score=score,
        category=category,
        components=snapshot["components"],
        reasons=reasons[:3],
        risks=risks[:3],
        missing_data=missing_data,
        snapshot=snapshot,
    )


def category_for_score(score: float) -> str:
    if score >= 80:
        return "strong buy"
    if score >= 65:
        return "buy"
    if score >= 40:
        return "hold"
    if score >= 25:
        return "sell"
    return "strong sell"


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _momentum_score(closes: list[float]) -> float:
    if len(closes) < 50:
        return 50.0
    latest = closes[-1]
    ma20 = statistics.fmean(closes[-20:])
    ma50 = statistics.fmean(closes[-50:])
    ma200 = statistics.fmean(closes[-200:]) if len(closes) >= 200 else statistics.fmean(closes)
    score = 50.0
    score += _pct(latest, ma20) * 80
    score += _pct(ma20, ma50) * 90
    score += _pct(ma50, ma200) * 60
    return max(0.0, min(100.0, score))


def _fundamentals_score(closes: list[float], full_quote: dict | None, sector: str | None) -> tuple[float, list[str]]:
    score = 50.0
    notes: list[str] = []
    fq = full_quote or {}

    pe = _safe_float(fq.get("pe"))
    eps = _safe_float(fq.get("eps"))

    if pe is not None:
        baseline = _sector_pe_baseline(sector)
        if pe <= 0:
            score -= 18
            notes.append(f"Veszteséges (P/E {pe:.1f}).")
        else:
            ratio = pe / baseline
            if ratio < 0.7:
                score += 22
                notes.append(f"P/E {pe:.1f} jóval a szektor átlag alatt ({baseline:.0f}).")
            elif ratio < 1.0:
                score += 12
                notes.append(f"P/E {pe:.1f} a szektor átlag alatt ({baseline:.0f}).")
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

    if eps is not None:
        if eps > 0:
            score += 9
            notes.append(f"Pozitív EPS: {eps:.2f}.")
        else:
            score -= 12
            notes.append(f"Negatív EPS: {eps:.2f} – profitabilitás nyomás alatt.")

    # MA trend quality from stored price history
    latest = closes[-1] if closes else None
    ma50 = statistics.fmean(closes[-50:]) if len(closes) >= 50 else None
    ma200 = statistics.fmean(closes[-200:]) if len(closes) >= 200 else None

    if latest and ma50 and ma200:
        if latest > ma50 > ma200:
            score += 12
            notes.append("Ár > 50d MA > 200d MA: tartós feltrend, minőségi jel.")
        elif latest > ma200 and ma50 < ma200:
            score += 3
            notes.append("Ár 200d MA felett, de a rövid trend gyengül.")
        elif latest < ma50 < ma200:
            score -= 12
            notes.append("Ár < 50d MA < 200d MA: tartós letrend.")
        elif latest < ma200:
            score -= 6
            notes.append("Ár 200d MA alatt: gyenge hosszú távú trend.")

    return max(5.0, min(95.0, score)), notes


def _valuation_score(latest: float, target: dict | None) -> float:
    consensus = (target or {}).get("target_consensus") or (target or {}).get("target_median")
    if not latest or not consensus:
        return 50.0
    upside = _pct(float(consensus), latest)
    return max(0.0, min(100.0, 50 + upside * 140))


def _events_score(filings: list[dict]) -> float:
    if not filings:
        return 50.0
    recent_cutoff = date.today() - timedelta(days=45)
    recent = [f for f in filings if f.get("filing_date") and f["filing_date"] >= recent_cutoff]
    return max(45.0, min(75.0, 50 + len(recent) * 6))


def _risk_score(closes: list[float]) -> float:
    if len(closes) < 30:
        return 50.0
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1]]
    vol = statistics.pstdev(returns[-60:]) if len(returns) >= 2 else 0
    peak = max(closes[-120:])
    drawdown = (closes[-1] / peak) - 1 if peak else 0
    score = 75 - vol * 520 + drawdown * 45
    return max(0.0, min(100.0, score))


def _reasons(
    symbol: str,
    closes: list[float],
    latest: float,
    target: dict | None,
    filings: list[dict],
    momentum: float,
    fundamentals: float,
    valuation: float,
    events: float,
    fund_notes: list[str],
) -> list[str]:
    reasons = []
    if len(closes) >= 50:
        change_20 = _pct(closes[-1], closes[-20])
        reasons.append(f"{symbol}: a 20 napos árfolyamváltozás {change_20:.1%}, momentum pont: {momentum:.1f}.")
    else:
        reasons.append(f"{symbol}: kevés árfolyamadat áll rendelkezésre, semleges momentum feltételezve.")
    if fund_notes:
        reasons.append(f"Fundamentum: {fund_notes[0]}")
    consensus = (target or {}).get("target_consensus") or (target or {}).get("target_median")
    if latest and consensus:
        reasons.append(f"Az elemzői célár alapján becsült upside: {_pct(float(consensus), latest):.1%}.")
    else:
        reasons.append("Céláradat hiányzik, ezért az értékeltségi komponens semleges.")
    if filings:
        reasons.append(f"Friss követett SEC események száma: {len(filings)}, eseménypont: {events:.1f}.")
    else:
        reasons.append("Nincs feldolgozott friss filing esemény.")
    if valuation >= 65:
        reasons.append("Az értékeltségi komponens pozitív.")
    return reasons


def _risks(closes: list[float], target_status: str, filings: list[dict], full_quote: dict | None) -> list[str]:
    risks = []
    if len(closes) >= 60:
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1]]
        vol = statistics.pstdev(returns[-60:]) if len(returns) >= 2 else 0
        if vol > 0.035:
            risks.append("Magas rövid távú volatilitás.")
        peak = max(closes[-120:])
        drawdown = (closes[-1] / peak) - 1 if peak else 0
        if drawdown < -0.2:
            risks.append(f"Jelentős visszaesés a közelmúlt csúcsától: {drawdown:.1%}.")
    fq = full_quote or {}
    pe = _safe_float(fq.get("pe"))
    eps = _safe_float(fq.get("eps"))
    if pe is not None and pe > 0:
        baseline = 22.0
        if pe / baseline > 2.0:
            risks.append(f"P/E {pe:.1f} – jelentős prémium a piaci átlaghoz képest.")
    if eps is not None and eps < 0:
        risks.append("Negatív EPS: a vállalat jelenleg veszteséges.")
    if target_status != "fmp":
        risks.append("Hiányzik vagy nem elérhető az elemzői céláradat.")
    if not filings:
        risks.append("A filingfigyelés nem teljes CIK vagy SEC adat nélkül.")
    return risks or ["Nincs kiugró kockázati jel a rendelkezésre álló adatokból."]


def _agent_debate(
    symbol: str,
    momentum: float,
    fundamentals: float,
    valuation: float,
    events: float,
    risk: float,
    missing_data: list[str],
) -> list[dict]:
    technical = _agent("Technical Analyst", momentum, f"{symbol} technikai trend- és momentumpontja: {momentum:.1f}.")
    fundamental = _agent("Fundamental Analyst", (fundamentals * 0.55 + valuation * 0.45), f"Fundamentum/értékeltség együtt: {fundamentals:.1f}/{valuation:.1f}.")
    news = _agent("SEC / News Analyst", events, f"Filing- és eseménykomponens: {events:.1f}.")
    bull_score = max(momentum, valuation, events)
    bear_score = 100 - min(momentum, valuation, risk)
    bull = _agent("Bull Researcher", bull_score, "A legerősebb pozitív érv a legjobb részpontszámból jön.")
    bear = _agent("Bear Researcher", 100 - bear_score, "A bear nézőpont a gyenge komponenseket és adatminőséget bünteti.")
    risk_manager = _agent("Risk Manager", risk, f"Kockázati pont: {risk:.1f}; hiányzó adatok száma: {len(missing_data)}.")
    pm_score = statistics.fmean([technical["score"], fundamental["score"], news["score"], bull["score"], bear["score"], risk_manager["score"]])
    manager = _agent("Portfolio Manager", pm_score, f"Végső agent konszenzus: {category_for_score(pm_score)}.")
    return [technical, fundamental, news, bull, bear, risk_manager, manager]


def _agent(name: str, score: float, thesis: str) -> dict:
    clean_score = round(max(0.0, min(100.0, score)), 1)
    return {
        "agent": name,
        "score": clean_score,
        "stance": category_for_score(clean_score),
        "thesis": thesis,
    }


def _pct(a: float, b: float) -> float:
    if not b:
        return 0.0
    return (a / b) - 1
