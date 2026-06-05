# Multi-agent architektúra

Inspiráció: TauricResearch TradingAgents.

## Implementált agent szerepek

1. **Technical Analyst** (`Trend Analyst` a preview módban)
   - Árfolyam-trend, momentum, 50/200 napos mozgóátlag.
   - Alpha Vantage és Yahoo Finance adatforrások.

2. **Fundamental Analyst**
   - P/E szektorbázishoz viszonyítva, EPS sign, MA-trend minősége.
   - FMP teljes quote adatokon alapul; kulcs nélkül MA-alapú fallback.

3. **Value Hunter** (preview) / **SEC & News Analyst** (backend)
   - Belépési értékeltség: 52-hetes sávpozíció, P/E összehasonlítás.
   - SEC filingek: 10-K, 10-Q, 8-K, 6-K.

4. **Sentiment Analyst** (preview) / **Bull Researcher** (backend)
   - Friss hírek katalizátorként; közelgő eredményjelentés bónusza.
   - A legerősebb pozitív érv összefoglalása.

5. **Bear Researcher**
   - A legerősebb eladási vagy óvatos érv összefoglalása.
   - Kockázati inverz logika: a gyenge komponenseket bünteti.

6. **Risk Manager**
   - Volatilitás, drawdown, hiányzó adatok száma.

7. **Portfolio Manager**
   - Végső konszenzus a 6 agent átlagából.
   - Divergencia-jelzéssel: nagy szórás → kisebb pozíció ajánlott.

## Architektúra-elvek

- Nem LangGraph: egyszerű Python orchestrator, determinisztikus JSON bemenet/kimenet.
- OpenAI csak összefoglalásra és vita-szövegre megy; a numerikus score determinisztikus.
- Minden agent output ticker/run szerint tárolva (Signal, Ranking táblák).
- Dashboardon elérhető az Agent debate blokk: minden agent stance és thesis látható.
- Külön jelzi: adat-alapú score, AI konszenzus, confidence szint.

## Tervezett fejlesztések

- **Memória és visszacsatolás**: korábbi ajánlások összevetése tényleges hozammal.
- **Adatminőségi jelzés** a rangsorlistán (jelenleg csak részletlapon látható).
- **Pozícióméret-javaslat** a backend API-n keresztül (run_local.py már tartalmazza).
- **Valós SEC-tartalom elemzése**: filing szöveg → OpenAI összefoglaló, nem csak metaadat.
- **Egységesített scoring**: backend és preview mód azonos súlyokat és logikát használjon.

## Kockázatok

- A multi-agent rendszer könnyen drágább és lassabb lesz.
- Egy rossz adatforrás sok agentet ugyanabba az irányba vihet.
- Az AI indoklás nem helyettesítheti a determinisztikus adatminőségi jelzést.
- A végső output továbbra is döntéstámogató, nem automatikus kereskedelmi utasítás.
