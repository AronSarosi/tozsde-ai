# Tőzsde AI Brand Guide

## Röviden

Tőzsde AI egy magyar tőzsdei döntéstámogató eszköz.

A márka legyen letisztult, gyorsan érthető és magabiztos. Ne legyen zsúfolt chart, robotfej, dollárjel, crypto hangulat vagy bankos unalom.

## Logóverziók

Három választható irány készült.

Új sötét háttéres irányok:

- `brand/tozsde-ai-dark-logo-directions.html`
- `brand/concepts/tozsde-ai-dark-concept-1-aperture.svg`
- `brand/concepts/tozsde-ai-dark-concept-2-monolith.svg`
- `brand/concepts/tozsde-ai-dark-concept-3-prism.svg`

Ezekben a `Tőzsde` fehér, az `AI` zöld. A bal oldali mark szándékosan nem használ pontokat és összekötött hálóvonalakat.

Pajzsvariációk a harmadik irányhoz:

- `brand/tozsde-ai-shield-variants.html`
- `brand/concepts/tozsde-ai-shield-variant-1-solid-green.svg`
- `brand/concepts/tozsde-ai-shield-variant-2-thick-outline.svg`
- `brand/concepts/tozsde-ai-shield-variant-3-filled-outline.svg`
- `brand/concepts/tozsde-ai-shield-variant-4-faceted-green.svg`
- `brand/concepts/tozsde-ai-shield-variant-5-minimal-badge.svg`

Teljesen újrakezdett friss irányok:

- `brand/tozsde-ai-fresh-directions.html`
- `brand/concepts/tozsde-ai-fresh-1-foundation-core.svg`
- `brand/concepts/tozsde-ai-fresh-2-growth-horizon.svg`
- `brand/concepts/tozsde-ai-fresh-3-evidence-lens.svg`
- `brand/concepts/tozsde-ai-fresh-4-safe-compound.svg`
- `brand/concepts/tozsde-ai-fresh-5-calm-grid.svg`
- `brand/concepts/tozsde-ai-fresh-6-capital-ring.svg`
- `brand/concepts/tozsde-ai-fresh-7-ai-seed.svg`
- `brand/concepts/tozsde-ai-fresh-8-signal-window.svg`
- `brand/concepts/tozsde-ai-fresh-9-portfolio-arc.svg`
- `brand/concepts/tozsde-ai-fresh-10-insight-stack.svg`

Ezek nem a pajzsos verzióból indulnak ki. A hangsúly a biztonságos, információalapú, AI-val támogatott befektetési döntésen van.

### 1. Signal

Ajánlott főverzió.

Egyszerű kör, egy emelkedő jel, egy AI-pont. Ez a legtisztább és legjobban skálázható.

- Fő logó: `frontend/src/assets/brand/tozsde-ai-logo-signal.svg`
- Sötét háttér: `frontend/src/assets/brand/tozsde-ai-logo-signal-reverse.svg`
- Ikon: `frontend/src/assets/brand/tozsde-ai-mark-signal.svg`

Alias fájlok, ha egyetlen alapértelmezett logót akarsz használni:

- `frontend/src/assets/brand/tozsde-ai-logo.svg`
- `frontend/src/assets/brand/tozsde-ai-logo-reverse.svg`
- `frontend/src/assets/brand/tozsde-ai-mark.svg`

### 2. Pillar

Erősebb pénzügyi jelleg.

Három emelkedő oszlop, egyszerű jelvonallal. Webapp ikonként és dashboardban jól működik.

- Fő logó: `frontend/src/assets/brand/tozsde-ai-logo-pillar.svg`
- Ikon: `frontend/src/assets/brand/tozsde-ai-mark-pillar.svg`

### 3. Focus

Termékesebb, apposabb irány.

Lekerekített keret, T-forma és jelvonal. Akkor jó, ha inkább szoftverterméknek akarod éreztetni, nem klasszikus pénzügyi márkának.

- Fő logó: `frontend/src/assets/brand/tozsde-ai-logo-focus.svg`
- Ikon: `frontend/src/assets/brand/tozsde-ai-mark-focus.svg`

## ImageGen referencia

A képgenerált irányok itt vannak:

- `brand/reference/tozsde-ai-imagegen-direction-1-circle.png`
- `brand/reference/tozsde-ai-imagegen-direction-2-monogram.png`
- `brand/reference/tozsde-ai-imagegen-direction-3-bars.png`

Fontos: a végleges logókat SVG-ben készítettem el, mert a magyar ékezet és a skálázhatóság így megbízható.

## Színek

Primary:

- Ink: `#111827`
- Graphite: `#1F2937`
- Signal green: `#22C55E`
- Cyan: `#06B6D4`
- Paper: `#F8FAFC`

Support:

- Mist: `#E2E8F0`
- Muted text: `#64748B`
- Warning: `#F59E0B`
- Danger: `#EF4444`

Használat:

- Az Ink legyen az alap szöveg és sötét háttér.
- A Signal green menjen pozitív jelzésekre és fő CTA-ra.
- A Cyan legyen AI-fókusz, aktív állapot, másodlagos adatkiemelés.
- Ne legyen az egész oldal kék-zöld. Kell fehér tér és nyugodt szürke.

## Tipográfia

Ajánlott:

- Display: Sora
- UI/body: Inter
- Fallback: system-ui

Minimum body méret: 16px.

Dashboardban, magyarázatoknál és fő felületeken inkább 17-18px. Ez fontos. A felhasználó pénzügyi döntést néz, ne kelljen hunyorítani.

## UI irány

Legyen olyan, mint egy tiszta döntési pult.

- Kevés dekoráció.
- Erős hierarchia.
- Nagy, olvasható számok.
- Rövid magyarázatok.
- 6-8px radius.
- Nincs nyíl a gombokban.
- Nincs generic AI marketing szöveg.

## Hang

Jó:

- "Erős jel, de magas kockázattal."
- "Ma nem a legjobb belépő."
- "A modell óvatos, mert az ár túl messze futott."

Rossz:

- "Unlock the power of next-generation AI investing."
- "Revolutionary AI insights for everyone."
- "Democratizing alpha."

## Webes használat

```jsx
import logo from "./assets/brand/tozsde-ai-logo.svg";

export function Header() {
  return <img src={logo} alt="Tőzsde AI" className="tozsde-logo" />;
}
```

CSS tokenek:

```css
@import "./assets/brand/tozsde-ai-brand.css";
```
