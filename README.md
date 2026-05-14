# Tőzsde AI

Helyi tőzsdei dontestamogato rendszer FastAPI backenddel, SQLite adatbazissal es React dashboarddal.

## Gyors inditas

## Megosztas Vercelen

Ez a repo Vercel-kompatibilis preview modban is fut.

1. Vercel dashboardon: Add New Project.
2. Importald ezt a GitHub repot: `AronSarosi/tozsde-ai`.
3. Root Directory: hagyd a repo gyokeren.
4. Framework Preset: Other, ha a Vercel nem ismeri fel automatikusan.
5. Build Command es Output Directory: hagyd uresen/alapertelmezetten.
6. Deploy.

API kulcsok nelkul is elindul. Ha kesobb elo adatokat akarsz, Vercel Environment Variables alatt add hozza:

```env
OPENAI_API_KEY=
ALPHAVANTAGE_API_KEY=
FMP_API_KEY=
```

### Azonnali preview, telepites es API kulcs nelkul

```powershell
python run_local.py
```

Nyisd meg: http://127.0.0.1:8765

Ez a verzio csak a beepitett Pythonra tamaszkodik. Hasznos arra, hogy azonnal lasd a feluletet es a rangsorolasi logikat, mielott API kulcsokat adsz hozza.

### Teljes FastAPI + React verzio

1. Masold a `.env.example` fajlt `.env` neven. API kulcsok nelkul is mukodik.
2. Futtasd:

```powershell
.\start.ps1
```

Backend: http://127.0.0.1:8000  
Dashboard: http://127.0.0.1:5173

API kulcs nelkul is elindul a rendszer. A dashboard kulon jelzi, melyik forras aktiv es melyik fallback modban fut.

## API kulcsok kesobbi hozzaadasa

Nem kell kodot modositani. Csak a `.env` fajlban toltsd ki az adott sort, majd inditsd ujra az appot:

```env
OPENAI_API_KEY=sk-...
ALPHAVANTAGE_API_KEY=...
FMP_API_KEY=...
```

Gyakorlati sorrend:

1. `OPENAI_API_KEY`: jobb magyar indoklasok es napi riport.
2. `ALPHAVANTAGE_API_KEY`: valos napi arfolyam idosor demo helyett.
3. `FMP_API_KEY`: valos celar es elemzoi konszenzus, ha erre is szukseg lesz.

SEC filingekhez nem kell kulcs.

## Fontos

Ez a rendszer dontestamogato es kutatasi eszkoz. Nem broker-integracio, nem automata kereskedes, es nem minosul penzugyi tanacsadasnak.
