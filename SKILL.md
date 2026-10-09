---
name: smart-factory-ui
description: Comprehensive design system and UI implementation guide for Solar Group Smart Factory and sub-module applications (Headcount, PPE Safety, Smart Production, Smart Operations, Smart Quality). Use when building, redesigning, or styling any Smart Factory application, dashboard, or component to achieve seamless visual continuity, brand adherence, and interaction parity.
---

# Solar Group Smart Factory — UI Design System & Sub-Module Redesign Skill

## Overview & Trigger Scenarios
Use this skill when:
1. **Designing or building new sub-module frontends** (e.g. Headcount AI, PPE Safety, IIoT Telemetry, OEE Analytics, Mixing SPC, Incident Reporting).
2. **Redesigning existing applications** to match the Solar Group Smart Factory design language so transitions between the master portal and sub-modules feel 100% native and seamless.
3. **Refactoring components, tokens, or layouts** to maintain strict brand adherence, visual hierarchy, and interaction mechanics.

---

## 🏛️ The 4 Non-Negotiable Core Design Laws

Every screen across the ecosystem must follow these four core principles:

1. **Hierarchy over Decoration**:
   - Every screen has **exactly one number or exception** that matters most (Display Hero).
   - Supporting metrics sit at **roughly ¼ of the hero's weight**.
   - Nothing else competes. If a screen needs a 4th support metric or a 3rd primary panel, it has not decided what it is for.

2. **Red is the Identity; Blue is the Interface**:
   - **Solar Red (`--brand-500` / `#ED1C24`)** appears in exactly three places:
     1. The **2px brand rule** capping a structural region (`.panel-brand`).
     2. The **tick** on an accented eyebrow (`.eyebrow-accent`).
     3. The **single highest-impact button** on a screen (`.btn-primary` — at most one visible at a time).
   - **Trust Blue (`--accent-*` / `#0d1128` to `#1a2d5e`)** carries all wayfinding: active navigation, links, focus rings, hover tints, icon accents, and info pills.
   - *Never use red as a general interactive or navigation color* — on an industrial plant screen, red reads as a standing emergency.

3. **Depth from Layering, Not Ornament**:
   - Surfaces step in four neutral tones (`--canvas`, `--surface`, `--surface-2`, `--surface-3`, `--surface-sunken`).
   - Surfaces are separated by crisp 1px hairlines (`--line`) and soft, honest shadows.
   - No loud gradients on content cards. Use the 2% engineering grid (`.grid-field`) on backgrounds to evoke precision engineering.

4. **Dark Grey is the Workhorse**:
   - Brand Dark Grey (`#212529` / `--ink`) carries all typography, display numbers, filled buttons (`.btn-ink`), and default chart marks (`--data` `#4a5157`).
   - Reaching for red is a deliberate decision; reaching for graphite is the default.

---

## 🎨 Design Tokens & Palette

Full token definitions live in [tokens.css](./references/tokens.css).

### 1. Brand & Wayfinding Palette
| Token | Hex Value | Role & Usage | Contrast |
|---|---|---|---|
| `--canvas` | `#f3f4f5` | Neutral viewport background | — |
| `--surface` | `#ffffff` | Elevated card & panel surface | — |
| `--surface-2` | `#fafbfb` | Sub-wells, interactive hover surface | — |
| `--surface-3` | `#f1f2f4` | Quiet pills, progress meter tracks | — |
| `--ink` | `#212529` | Headings, display metrics, default filled button | 15.3:1 |
| `--ink-2` | `#464c53` | Standard body copy | 8.6:1 |
| `--ink-3` | `#707070` | Secondary labels, timestamps, metadata | 5.3:1 |
| `--line` | `#e6e8ea` | Standard 1px divider and border | — |
| `--brand-500` | `#ed1c24` | Solar Red identity hex (caps, ticks, logo) | — |
| `--brand-600` | `#d31017` | Highest-impact CTA fill (`.btn-primary`) | 5.0:1 |
| `--accent-200`| `#c7e0f3` | Powder Blue (selection highlight) | — |
| `--accent-600`| `#1f3f80` | Wayfinding active fill carrying white type | 10.1:1 |
| `--accent-700`| `#1a2d5e` | Wayfinding active text and icons on white | 13.3:1 |
| `--data` | `#4a5157` | Default chart lines, bars, and meters (Graphite) | — |

### 2. Semantic Status & Life-Safety
| Token | Surface / Border | Semantic Role |
|---|---|---|
| `--ok` (`#0a6c40`) | `#eefaf3` / `#a8e6c4` | Normal operations, compliant metrics |
| `--warn` (`#a85908`) | `#fff9ec` / `#fbdd9a` | Nearing threshold, operator attention required |
| `--critical` (`#b42318`) | `#fdf3f2` / `#f6cac6` | Emergency stop, interlock trip, limit exceeded |

> [!CAUTION]
> **Life-Safety Outranks the Brand by Form, Not Hue:**
> Stop-work and emergency states use `.alarm-block` — a solid crimson fill, white type, warning glyph, and a pulsing leading rail. An operator resolves mass and motion before hue. Never use `.alarm-block` for non-safety notices.

### 3. 5 Pillars (Domain Categorization ONLY — Never for Status)
- **Smart Security**: `--p-sec` (`#1f5fa8`)
- **Smart Safety**: `--p-saf` (`#2f8f4e`)
- **Smart Production**: `--p-pro` (`#b56a0a`)
- **Smart Operations**: `--p-ops` (`#10808f`)
- **Smart Quality**: `--p-qua` (`#7b3fa0`)

---

## 🔤 Typography & Brand Rules

- **Typeface**: **Montserrat** across all applications.
- **Three Weights ONLY**:
  1. **Heading**: Bold (`700`)
  2. **Sub-heading / Label**: Medium (`500`)
  3. **Body**: Regular (`400`)
- **Strict Sentence Case**: Never use `text-transform: uppercase` or ALL-CAPS micro labels. Separation comes from weight and color.
- **Tabular Numerics**: Always apply `font-variant-numeric: tabular-nums` (`.tabular`) on metrics so live updates do not jitter.

---

## 📐 Solar Logo Standards (`Logo.tsx` / `SolarLogo.jsx`)

1. **Unboxed & Unconstrained Presentation**:
   - ❌ **Never enclose the logo inside an artificial card, bordered box, or shadow container** — this creates visual friction and looks constrained.
   - The logo must float naturally directly on the header, sidebar, or surface canvas with transparent framing.
2. **Clear Space**: Always enforce `1x` clear space on all sides (`1x` = wordmark cap height = total height / 1.9).
3. **Minimum Size**: Minimum digital width is `55px`.
4. **Proportions**: Fixed ratio of `4.409:1` (`1186px × 269px` cropped bounds). Never stretch or letterbox the logo canvas.
5. Use `public/brand/solar-logo.png` or `public/logo/logo.png`.

---

## 🚫 Zero Generic / Decorative Symbols Rule

1. **No Decorative Icon Clutter**:
   - ❌ Never use generic/decorative symbols (e.g., sparkles, random lightning bolts, emojis, or arbitrary icons preceding standard text labels).
   - ❌ Never prefix standard form input labels (`label`) with decorative icons.
2. **Functional Icons Only**:
   - Icons must be strictly purposeful and semantic (e.g., `<Video>` for camera stream, `<Cpu>` for compute hardware, `<Download>` for file export, `<RefreshCw>` for reload).
3. **Clean Brand Typography**:
   - Use clean typographic identity (e.g. `Solar Smart Factory`) rather than arbitrary icon badges in the navigation rail.

---

## 🏗️ Canonical Screen Layout Blueprint

Every sub-module dashboard adopts the **6-Slot Hierarchy**:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [1. Context Header] Where am I • Whose data is this • Live Telemetry Freshness Pill    │
├────────────────────────────────────────────────────────┬───────────────────────────────┤
│ [2. Hero Attention Exception]                          │ [3. World View / Live Map]    │
│  - 2px Solar Red Top Cap (.panel-brand)                │  - Interactive floor plan,    │
│  - 1 Display Number or Exception Diagnostic            │    asset list, or stream      │
│  - Specific Written Recommendation                     │  - Expandable to <Sheet />    │
│  - Max 1 Primary Action (.btn-primary)                 │                               │
├────────────────────────────────────────────────────────┴───────────────────────────────┤
│ [4. Supporting Metric Trio] Three KPIs at ~¼ hero weight (.panel with .meter)         │
├────────────────────────────────────────────────────────┬───────────────────────────────┤
│ [5. Primary Action Panel]                              │ [6. Secondary Detail Panel]   │
│  - Active batch control, machine logbook, or queue     │  - Historical breakdown,      │
│  - Interactive list rows with pointer feedback         │    shift notes, or SPC trend  │
└────────────────────────────────────────────────────────┴───────────────────────────────┘
```

### Two-Page Scroll-Snap Architecture
For comprehensive dashboards, split slots into two viewport-height pages via native CSS scroll-snap:
- **Page 1 (Overview)**: Header, Hero Attention Item, Supporting Metric Trio, World Preview.
- **Page 2 (Action & Detail)**: Primary Action Tables, Diagnostics, Deep Audit Trail.
- Use `.snap-scroller` and `.snap-page` with fixed `PageIndicator` navigation.

---

## 🧱 Component Class Blueprints

Ready-to-use markup and React code are detailed in [components.md](./references/components.md).

### 1. Surfaces & Cards
- `.panel`: `bg-surface border border-line rounded-[var(--r-lg)] shadow-sm`
- `.panel-raised`: `bg-surface border border-line rounded-[var(--r-lg)] shadow`
- `.panel-brand`: Includes the signature 2px gradient Solar Red top cap.
- `.well`: `bg-surface-2 border border-line rounded-[var(--r-md)]`
- `.grid-field`: 22px technical modular grid texture at 2.8% opacity.

### 2. Labels & Headings
- `.display`: `font-bold tracking-[-0.038em] text-ink tabular` with `.unit` (`text-[0.4em] text-ink-3`).
- `.eyebrow`: `text-[11px] font-medium text-ink-3`.
- `.eyebrow-accent`: `text-[11px] font-bold text-accent-700` with 14px Solar Red tick (`::before`).
- `.rule-head`: Section title with expanding 1px trailing hairline.

### 3. Buttons & Controls
- `.btn`: Standard button (`36px` height, `13px` type, `font-weight: 700`, active scale `0.975`).
- `.btn-primary`: Solar Red fill (`var(--brand-600)`) with `--shadow-brand` — **max 1 per screen**.
- `.btn-ink`: Dark Grey fill (`var(--ink)`) with `--shadow-ink` — default filled button.
- `.btn-outline`: Trust Blue border and text for secondary wayfinding.
- `.btn-quiet`: Borderless button for toolbars.

### 4. Status Pills
- `.pill-ok`: `bg-ok-surface text-ok border-ok-line`
- `.pill-warn`: `bg-warn-surface text-warn border-warn-line`
- `.pill-critical`: `bg-critical-surface text-critical border-critical-line`
- `.pill-info`: `bg-accent-50 text-accent-700 border-accent-100`

### 5. Data Visualizations
- Default to **Graphite (`--data`)**, never red or accent unless crossing an operational limit.
- ISO 22400 standard metrics: OEE, First Pass Yield (FPY), Scrap Rate, MTBF/MTTR, Cpk.

---

## 🚀 Sub-Module Redesign Step-by-Step Migration Playbook

When converting an existing sub-module (or creating a new one) to this design language:

### Step 1: Install Fonts & Tokens
1. Embed **Montserrat** (weights 400, 500, 700).
2. Inject [tokens.css](./references/tokens.css) into the application's root stylesheet.
3. Configure Tailwind theme extensions with `--color-canvas`, `--color-ink`, `--color-brand-500`, `--color-accent-700`, etc.

### Step 2: Strip Incompatible Styles
1. ❌ Remove all upper-case micro-labels (`uppercase` / `tracking-widest`). Replace with sentence-case `.eyebrow` or `.label`.
2. ❌ Remove generic Tailwind blues/reds/slates (`bg-blue-600`, `bg-red-500`, `bg-slate-900`). Replace with semantic tokens.
3. ❌ Remove decorative gradients and heavy glowing borders. Replace with clean `.panel` surfaces.

### Step 3: Implement the Layout Shell
1. Add the **Context Header**: Show Plant Name, Production House, Active Shift, and Telemetry Connection Status (`<span class="live-dot"></span>`).
2. Add the **Navigation Rail**: Trust Blue active pill (`--accent-50` background, `--accent-700` text).

### Step 4: Refactor KPI & Hero Cards
1. Identify the **single primary exception/metric** for the screen. Place it in a `.panel-raised.panel-brand` card with a written recommendation.
2. Group supporting KPIs into a **3-column support row** at ¼ visual weight with linear `.meter` indicators.

### Step 5: Align Button Actions
1. Find the single most important action on the page and make it `.btn-primary` (Solar Red).
2. Convert all other primary submit/action buttons to `.btn-ink` (Graphite).
3. Convert secondary actions to `.btn` or `.btn-outline`.

### Step 6: Apply Micro-Animations
1. Use **critically damped springs** (`bounce: 0`, `duration: 0.4s`).
2. Choreograph entrances with `staggerParent` (40ms stagger) and `riseItem` (translateY 10px to 0).
3. Ensure all animations respect `prefers-reduced-motion`.

---

## ✅ Design Compliance Checklist

Before deploying any sub-module UI, verify against this checklist:

- [ ] **Typeface**: 100% Montserrat in 400, 500, or 700 weight only.
- [ ] **Case**: Sentence case across all titles, buttons, badges, and eyebrows (0 uppercase transforms).
- [ ] **Red Usage**: Solar Red is limited to the brand cap, eyebrow ticks, and at most ONE primary CTA.
- [ ] **Wayfinding**: All active nav tabs, links, and focus rings use Trust Blue (`--accent-*`).
- [ ] **Charts & Meters**: Default series color is graphite (`--data`), only turning semantic red/orange when thresholds are breached.
- [ ] **Alarms**: Only true life-safety stop-work events use `.alarm-block`.
- [ ] **Numbers**: All live metrics use tabular numbers (`.tabular`).
- [ ] **Logo**: Enforces clear space (`height / 1.9`), digital width >= 55px, and **floats unboxed/unconstrained** without artificial card borders or drop shadows.
- [ ] **Symbols**: Zero generic/decorative icons (no sparkles, random lightning bolts, or redundant icon prefixes on form labels).
