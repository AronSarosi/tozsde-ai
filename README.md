# Tőzsde AI

Helyi tőzsdei döntéstámogató rendszer FastAPI backenddel, SQLite adatbázissal és React dashboarddal.

## Gyors indítás

## Megosztás Vercelen

Ez a repo Vercel-kompatibilis preview módban is fut.

1. Vercel dashboardon: Add New Project.
2. Importáld ezt a GitHub repot: `AronSarosi/tozsde-ai`.
3. Root Directory: hagyd a repo gyökerén.
4. Framework Preset: Other, ha a Vercel nem ismeri fel automatikusan.
5. Build Command és Output Directory: hagyd üresen/alapértelmezetten.
6. Deploy.

API kulcsok nélkül is elindul. Ha később élő adatokat akarsz, Vercel Environment Variables alatt add hozzá:

```env
OPENAI_API_KEY=
ALPHAVANTAGE_API_KEY=
FMP_API_KEY=
```

### Azonnali preview, telepítés és API kulcs nélkül

```powershell
python run_local.py
```

Nyisd meg: http://127.0.0.1:8765

Ez a verzió csak a beépített Pythonra támaszkodik. Hasznos arra, hogy azonnal lásd a felületet és a rangsorolási logikát, mielőtt API kulcsokat adsz hozzá.

### Teljes FastAPI + React verzió

1. Másold a `.env.example` fájlt `.env` néven. API kulcsok nélkül is működik.
2. Futtasd:

```powershell
.\start.ps1
```

Backend: http://127.0.0.1:8000  
Dashboard: http://127.0.0.1:5173

API kulcs nélkül is elindul a rendszer. A dashboard külön jelzi, melyik forrás aktív és melyik fallback módban fut.

## API kulcsok utólagos hozzáadása

Nem kell kódot módosítani. Csak a `.env` fájlban töltsd ki az adott sort, majd indítsd újra az appot:

```env
OPENAI_API_KEY=sk-...
ALPHAVANTAGE_API_KEY=...
FMP_API_KEY=...
```

Gyakorlati sorrend:

1. `OPENAI_API_KEY`: jobb magyar indoklások és napi riport.
2. `ALPHAVANTAGE_API_KEY`: valós napi árfolyam idősor demo helyett.
3. `FMP_API_KEY`: valós célár és elemzői konszenzus, fundamentum-adatok (P/E, EPS).

SEC filingekhez nem kell kulcs.

## Fontos

Ez a rendszer döntéstámogató és kutatási eszköz. Nem broker-integráció, nem automata kereskedés, és nem minősül pénzügyi tanácsadásnak.
