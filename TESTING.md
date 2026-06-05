# Tőzsde AI tesztelés

## 1. Azonnali preview teszt

```powershell
python run_local.py
```

Nyisd meg:

```text
http://127.0.0.1:8000
```

Ellenőrizd:

- A fejlécben `Tőzsde AI napi rangsor` látszik.
- Az OpenAI, Alpha Vantage és FMP státusz `aktív`.
- A `Tickerek` szám 70.
- A rating skála 5 fokozatú: `strong buy`, `buy`, `hold`, `sell`, `strong sell`.
- A kereső működik tickerre, például `NVDA`, `TSM`, `V`, `LMT`.
- A kategóriaváltó működik: `all`, `strong buy`, `buy`, `hold`, `sell`, `strong sell`.
- Egy sorra kattintva a jobb oldali részvény-részlet frissül.
- A részvény-részletben látszik az `Agent consensus` blokk.

## 2. Kulcsok ellenőrzése értékek kiírása nélkül

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([^#=]+)=(.*)$') {
    $name=$matches[1].Trim()
    $value=$matches[2]
    if ($value.Trim().Length -gt 0) { "$name=<set>" } else { "$name=<empty>" }
  }
}
```

## 3. Portfólió lista ellenőrzése

```powershell
@'
import run_local
print(len(run_local.load_portfolio()))
print([s["symbol"] for s in run_local.load_portfolio()[-10:]])
'@ | python -
```

Elvárt eredmény: `70`.

## 4. Python szintaxis ellenőrzés

```powershell
python -m compileall run_local.py backend\app
```

## 5. Teljes FastAPI + React verzió

A teljes verzióhoz a Python és Node csomagokat telepíteni kell. Ha a hálózati vagy sandbox korlát blokkolja a telepítést, a preview verzióval továbbra is lehet tesztelni a portfóliót, kulcs-státuszt és rangsor logikát.

```powershell
.\start.ps1
```

Elérés:

- Backend: `http://127.0.0.1:8000`
- Dashboard: `http://127.0.0.1:5173`
