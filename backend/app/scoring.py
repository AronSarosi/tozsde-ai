from dataclasses import dataclass
from datetime import date, timedelta
import json
import statistics


@dataclass
class ScoreResult:
    score: float
    category: str
    components: dict[str, float]
    reasons: list[str]
    risks: list[str]
    missing_data: list[str]
    snapshot: dict


def score_stock(symbol: str, prices: list[dict], filings: list[dict], target: dict | None, target_status: str) -> ScoreResult:
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
    fundamentals = 50.0
    valuation = _valuation_score(latest, target)
    events = _events_score(filings)
    risk = _risk_score(closes)

    weighted = momentum * 0.25 + fundamentals * 0.25 + valuation * 0.20 + events * 0.15 + risk * 0.15
    base_score = round(max(0.0, min(100.0, weighted)), 1)
    agents = _agent_debate(symbol, momentum, fundamentals, valuation, events, risk, missing_data)
    agent_score = statistics.fmean(agent["score"] for agent in agents)
    score = round(max(0.0, min(100.0, base_score * 0.65 + agent_score * 0.35)), 1)
    category = category_for_score(score)

    reasons = _reasons(symbol, closes, latest, target, filings, momentum, valuation, events)
    reasons.insert(0, f"Multi-agent konszenzus: {category}, konszenzuspont: {score:.1f}.")
    risks = _risks(closes, target_status, filings)
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


def _reasons(symbol: str, closes: list[float], latest: float, target: dict | None, filings: list[dict], momentum: float, valuation: float, events: float) -> list[str]:
    reasons = []
    if len(closes) >= 50:
        change_20 = _pct(closes[-1], closes[-20])
        reasons.append(f"{symbol}: a 20 napos árfolyamváltozás {change_20:.1%}, momentum pont: {momentum:.1f}.")
    else:
        reasons.append(f"{symbol}: kevés árfolyamadat áll rendelkezésre, semleges momentum feltételezve.")
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


def _risks(closes: list[float], target_status: str, filings: list[dict]) -> list[str]:
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
