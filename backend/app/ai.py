import json

from openai import OpenAI


def build_stock_summary(openai_api_key: str | None, snapshot: dict, reasons: list[str], risks: list[str]) -> str:
    if not openai_api_key:
        return _fallback_stock_summary(snapshot, reasons, risks)

    client = OpenAI(api_key=openai_api_key)
    prompt = (
        "Készíts rövid, magyar nyelvű, befektetői döntéstámogató összefoglalót. "
        "Csak a kapott JSON adatokat használd, ne találj ki hiányzó információt. "
        "Legyen benne: javaslati kategória, fő okok, fő kockázatok, hiányzó adatok."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"snapshot": snapshot, "reasons": reasons, "risks": risks}, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=260,
        )
        return response.choices[0].message.content or _fallback_stock_summary(snapshot, reasons, risks)
    except Exception:
        return _fallback_stock_summary(snapshot, reasons, risks)


def build_report(openai_api_key: str | None, rankings: list[dict]) -> str:
    if not openai_api_key:
        return _fallback_report(rankings)

    client = OpenAI(api_key=openai_api_key)
    prompt = (
        "Készíts magyar napi portfólióriportot a megadott rangsorból. "
        "Ne adj pénzügyi tanácsot, döntéstámogató megfogalmazást használj. "
        "Emeld ki a strong buy, buy, hold, sell és strong sell csoportokat, valamint a hiányzó adatokat."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(rankings[:70], ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=1100,
        )
        return response.choices[0].message.content or _fallback_report(rankings)
    except Exception:
        return _fallback_report(rankings)


def _fallback_stock_summary(snapshot: dict, reasons: list[str], risks: list[str]) -> str:
    missing = snapshot.get("missing_data") or []
    return (
        f"Pontszám-komponensek alapján a rendszer kategóriája: {snapshot.get('components', {})}. "
        f"Fő okok: {' '.join(reasons)} "
        f"Kockázatok: {' '.join(risks)} "
        f"Hiányzó adatok: {', '.join(missing) if missing else 'nincs jelölve'}."
    )


def _fallback_report(rankings: list[dict]) -> str:
    groups = {"strong buy": [], "buy": [], "hold": [], "sell": [], "strong sell": []}
    for item in rankings:
        groups.setdefault(item["category"], []).append(item)
    lines = [
        "# Napi tőzsdei döntéstámogató riport",
        "",
        "Ez nem pénzügyi tanácsadás, hanem adat alapú döntéstámogató összefoglaló.",
        "",
    ]
    for category, items in groups.items():
        lines.append(f"## {category}")
        if not items:
            lines.append("- Nincs ilyen kategóriájú ticker.")
            continue
        for item in items[:10]:
            reason = item["reasons"][0] if item.get("reasons") else "Nincs indoklás."
            lines.append(f"- {item['symbol']} ({item['score']}): {reason}")
        lines.append("")
    return "\n".join(lines)
