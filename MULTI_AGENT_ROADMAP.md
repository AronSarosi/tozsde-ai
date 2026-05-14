# Multi-agent fejlesztesi terv

Inspiracio: TauricResearch TradingAgents.

## Mit erdemes atvenni

- Kulon analyst szerepek: technikai, fundamentális, news/SEC, sentiment.
- Bull es bear vita: minden tickerhez legyen pozitiv es negativ befektetesi eset.
- Risk panel: agressziv, semleges es konzervativ kockazati nezet.
- Portfolio manager: a végső döntést ne egyetlen score adja, hanem konszenzus.
- Memoria: a korabbi javaslatokat kesobb hasonlitsa ossze a tenyleges hozammal.
- Strukturalt output: `strong buy / buy / hold / sell / strong sell`.

## Javasolt sajat architektura

1. `Data Analyst`
   - Arfolyam, volumen, momentum, drawdown.
   - Alpha Vantage es kesobb mas adatforrasok.

2. `Fundamental Analyst`
   - FMP célár, konszenzus, fundamentális mutatok.
   - Hianyzo adatnal semleges, explicit `missing_data`.

3. `SEC / News Analyst`
   - SEC filingek, 10-K, 10-Q, 8-K, 6-K.
   - OpenAI osszefoglalo csak tarolt inputbol.

4. `Bull Researcher`
   - A legerosebb veteli erv osszefoglalasa.

5. `Bear Researcher`
   - A legerosebb eladasi vagy ovatos erv osszefoglalasa.

6. `Risk Manager`
   - Volatilitas, drawdown, szektor-koncentracio, adatminoseg.

7. `Portfolio Manager`
   - Vegso kategoria es indoklas.
   - Kulon jelzi: adat-alapu score, AI konszenzus, confidence.

## V1 implementacios sorrend

1. Ne epitsunk be LangGraphot rogton; eloszor legyen egyszeru Python orchestrator.
2. Minden agent egy determinisztikus JSON bemenetet es JSON kimenetet kapjon.
3. OpenAI csak osszefoglalasra es vita-szovegre menjen, a numerikus score maradjon determinisztikus.
4. Menteni kell minden agent outputot ticker/run szerint, hogy visszakeresheto legyen.
5. Dashboardon legyen `Agent debate` ful: bull, bear, risk, final consensus.

## Kockázatok

- A multi-agent rendszer konnyen dragabb es lassabb lesz.
- Egy rossz adatforras sok agentet ugyanabba az iranyba vihet.
- Az AI indoklas nem helyettesitheti a determinisztikus adatminosegi jelzest.
- A vegso output tovabbra is döntéstámogató, nem automatikus kereskedesi utasitas.
