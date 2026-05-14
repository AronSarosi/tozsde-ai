# Tőzsde AI teszteles

## 1. Azonnali preview teszt

```powershell
python run_local.py
```

Nyisd meg:

```text
http://127.0.0.1:8000
```

Ellenorizd:

- A fejlécben `Tőzsde AI napi rangsor` latszik.
- Az OpenAI, Alpha Vantage es FMP statusz `aktiv`.
- A `Tickerek` szam 70.
- A rating skala 5 fokozatu: `strong buy`, `buy`, `hold`, `sell`, `strong sell`.
- A kereso mukodik tickerre, peldaul `NVDA`, `TSM`, `V`, `LMT`.
- A kategoriavalto mukodik: `all`, `strong buy`, `buy`, `hold`, `sell`, `strong sell`.
- Egy sorra kattintva a jobb oldali reszveny-reszlet frissul.
- A reszveny-reszletben latszik az `Agent consensus` blokk.

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

## 3. Portfolio lista ellenőrzése

```powershell
@'
import run_local
print(len(run_local.load_portfolio()))
print([s["symbol"] for s in run_local.load_portfolio()[-10:]])
'@ | python -
```

Elvart eredmeny: `70`.

## 4. Python szintaxis ellenorzes

```powershell
python -m compileall run_local.py backend\app
```

## 5. Teljes FastAPI + React verzio

A teljes verziohoz a Python es Node csomagokat telepiteni kell. Ha a halozati vagy sandbox korlat blokkolja a telepitest, a preview verzioval tovabbra is lehet tesztelni a portfoliot, kulcs-statuszt es rangsor logikat.

```powershell
.\start.ps1
```

Eleres:

- Backend: `http://127.0.0.1:8000`
- Dashboard: `http://127.0.0.1:5173`
