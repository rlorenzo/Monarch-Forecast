---
name: Monarch Forecast
description: A warm, editorial almanac for personal cash-flow forecasting.
colors:
  coral: "#d97a64"
  coral-deep: "#b8523f"
  coral-tint: "#fae3d8"
  signal-positive: "#2e9764"
  signal-negative: "#d04632"
  signal-threshold: "#d4a657"
  paper: "#faf6f3"
  paper-2: "#f4ece6"
  paper-3: "#ece1d8"
  rule: "#d6c5ba"
  ink: "#392b24"
  ink-2: "#5e4f47"
  ink-3: "#8c7c72"
  ink-dark: "#22150f"
  ink-dark-2: "#2c1f17"
  ink-dark-3: "#3a2a22"
  rule-dark: "#534138"
  paper-dark: "#eadfd4"
  paper-dark-2: "#c4b0a3"
  paper-dark-3: "#907f73"
typography:
  display:
    fontFamily: "Fraunces, 'Source Serif Pro', Georgia, serif"
    fontSize: "38"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.01em"
    fontFeature: "tnum, lnum"
  headline:
    fontFamily: "Fraunces, 'Source Serif Pro', Georgia, serif"
    fontSize: "24"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.005em"
    fontFeature: "tnum, lnum"
  title:
    fontFamily: "Inter, 'Helvetica Neue', system-ui, sans-serif"
    fontSize: "16"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "Inter, 'Helvetica Neue', system-ui, sans-serif"
    fontSize: "13"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
    fontFeature: "tnum, lnum"
  label:
    fontFamily: "Inter, 'Helvetica Neue', system-ui, sans-serif"
    fontSize: "11"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.06em"
rounded:
  xs: "3px"
  sm: "6px"
  md: "10px"
  lg: "14px"
spacing:
  2xs: "2px"
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "32px"
  3xl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.coral}"
    textColor: "{colors.paper}"
    typography: "{typography.title}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.coral-deep}"
    textColor: "{colors.paper}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
  button-ghost-hover:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
  input-text:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  input-text-focus:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  card-quiet:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "20px 24px"
  chip-recurring:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.xs}"
    padding: "2px 6px"
  nav-tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    typography: "{typography.title}"
    padding: "8px 12px"
  nav-tab-active:
    backgroundColor: "transparent"
    textColor: "{colors.coral}"
---

# Design System: Monarch Forecast

## 1. Overview

**Creative North Star: "The Pocket Almanac"**

A small, opinionated, dated book of forward-looking certainties. The almanac has a posture: it tells you what's coming this week and stakes its name on the answer. It does not hedge, it does not advertise to you, it does not gamify your money. The paper is warm. The ink is dark. The typography is editorial — a serif that believes in the verdict it just rendered, paired with a sans that handles the supporting prose without ego.

This system explicitly rejects every reflex of the "personal finance dashboard" category. Stock Material 3 with its blue seed and identical elevation reads as an unfinished Flutter app — that is the current state and the thing we are moving away from. No neon-on-black, no gradient text, no number tickers, no glassmorphism, no marketing-style hero cards. No pie charts and no category-explorer bait. The chart is the product; everything else is paper around it.

Density is high — this is a financial tool, not a magazine landing page — but rhythm holds it together. Section headers in serif. Numbers in tabular figures. Generous-enough breathing room between sections, tight density within them. Color reserved for signal, never for decoration. The only saturated colors on screen at rest are the coral brand mark and any active threshold-crossing marker on the chart.

**Key Characteristics:**

- Editorial serif display (Fraunces) paired with a humanist sans (Inter) for everything else.
- Warm clay-toned neutrals — paper and ink, not gray and white. The neutrals are tinted toward the coral hue (30°) at low chroma (0.005–0.015).
- One brand accent: a warm coral. Used on ≤10% of any screen at rest. Reserved for the brand mark, primary CTA, active tab indicator, and the chart's headline series.
- Three signal hues — positive (green), negative (red), threshold (amber) — used only for forecast meaning. Never decorative.
- Restrained motion. State changes only — hover, focus, color shifts. No entrances, no scroll choreography, no number tickers. The "glance" must not wait on animation.
- Light and dark themes are designed first-class equals, not primary-and-fallback.
- Tabular lining figures everywhere financial. Dollar columns must lock.

## 2. Colors: The Paper-and-Ink Palette

A warm, hue-tinted neutral system, anchored by a single coral accent and three signal hues for forecast direction. Every neutral is tinted toward hue 30 (coral) at chroma 0.005–0.015, so paper and ink share the brand's warmth without ever asserting color. The frontmatter carries sRGB hex approximations for direct use in Flet; the OKLCH values below are the canonical source and what new tokens should be derived from.

### Primary

- **Coral** (`#d97a64` / `oklch(64% 0.14 30)`): The brand accent. Used on the brand mark, the primary CTA, the active tab indicator, the chart's headline projected-balance line, and the focused-input outline. Nothing else.
- **Coral Deep** (`#b8523f` / `oklch(54% 0.16 28)`): Hover and active state for any coral surface (buttons, the threshold crossing's emphasis ring). Never used as a resting color.
- **Coral Tint** (`#fae3d8` / `oklch(94% 0.04 30)`): The light-mode emphasis background — selected list rows, focused-input fill at rest, hover tint behind ghost buttons. The dark-mode equivalent is `ink-dark-3` with a coral-tinted overlay.

### Signal (forecast meaning only)

- **Signal Positive** (`#2e9764` / `oklch(58% 0.13 150)`): Surplus rows in the transactions table, balance trajectory above the threshold, income deltas in the dashboard summary. Always paired with a `+` glyph or `semantics_label` so meaning survives color-blindness.
- **Signal Negative** (`#d04632` / `oklch(58% 0.18 25)`): Below-threshold balance, overdraft alerts, expense rows. Always paired with a `−` glyph or `semantics_label`. Visually distinct from coral by chroma — coral is muted (0.14), signal-negative is sharp (0.18) — so the brand color never reads as alarm.
- **Signal Threshold** (`#d4a657` / `oklch(72% 0.12 70)`): The safety-threshold line on the chart, threshold-crossing markers, "approaching shortfall" alerts. Amber is reserved for this one role.

### Neutral — Light Theme

- **Paper** (`#faf6f3` / `oklch(98% 0.005 30)`): Canonical surface. Window background, card fill at rest, input fill. Never `#fff`.
- **Paper 2** (`#f4ece6` / `oklch(96% 0.006 30)`): The first tonal step. Used for tab strip background, hover fills on ghost surfaces, the alternating row tint in the transactions table.
- **Paper 3** (`#ece1d8` / `oklch(93% 0.008 30)`): Hairline-emphasis backgrounds — selected row in a calendar popover, info-banner fills, the highlighted "today" column on the chart.
- **Rule** (`#d6c5ba` / `oklch(86% 0.008 30)`): All 1px borders, dividers, table outlines, chart axes. The only acceptable line color in light mode.
- **Ink** (`#392b24` / `oklch(22% 0.015 30)`): Body text and headline text. Replaces `ON_SURFACE` everywhere. Never `#000`.
- **Ink 2** (`#5e4f47` / `oklch(38% 0.013 30)`): Secondary text — column subtitles, helper text under inputs, "Forecast window" labels. Replaces `ON_SURFACE_VARIANT`.
- **Ink 3** (`#8c7c72` / `oklch(56% 0.012 30)`): Tertiary text — disabled labels, week-day headers in the calendar, axis tick labels on the chart. Must still meet WCAG AA against `paper`.

### Neutral — Dark Theme

- **Ink Dark** (`#22150f` / `oklch(14% 0.014 30)`): Canonical surface. The dark theme is not navy or charcoal — it is the same warm clay hue, just dimmed. Window background, card fill at rest.
- **Ink Dark 2** (`#2c1f17` / `oklch(18% 0.012 30)`): First tonal step in dark — tab strip background, hover fill on ghost surfaces.
- **Ink Dark 3** (`#3a2a22` / `oklch(24% 0.012 30)`): Emphasis fill in dark — selected row, info-banner, the highlighted "today" column on the chart.
- **Rule Dark** (`#534138` / `oklch(34% 0.012 30)`): Borders, dividers, table outlines in dark.
- **Paper Dark** (`#eadfd4` / `oklch(92% 0.008 30)`): Body text and headlines in dark.
- **Paper Dark 2** (`#c4b0a3` / `oklch(76% 0.011 30)`): Secondary text in dark.
- **Paper Dark 3** (`#907f73` / `oklch(58% 0.012 30)`): Tertiary text in dark.

### Named Rules

**The One Voice Rule.** Coral appears on ≤10% of any screen at rest. The brand mark, the primary CTA, and the projected-balance line on the chart together must consume less than a tenth of the visible pixels. If two coral surfaces want the same screen, one of them was wrong. Hover states do not count against this budget — they are momentary.

**The Signal Separation Rule.** Coral is brand. Green is surplus. Red is shortfall. Amber is the safety threshold. These four hues live in disjoint roles and are never substituted. Do not use coral to mean alarm. Do not use red to mean "active." Do not introduce a fifth saturated color.

**The Warmed-Neutral Rule.** Every neutral on screen is tinted toward hue 30 at chroma 0.005–0.015. No untinted `#fff`, `#000`, or pure grays. The clay warmth is what makes this app not feel like a banking dashboard.

## 3. Typography: Editorial Serif Meets Humanist Sans

**Display Font:** Fraunces (with `Source Serif Pro`, Georgia, serif as fallbacks)
**Body Font:** Inter (with `Helvetica Neue`, `system-ui`, sans-serif as fallbacks)

**Character:** Fraunces is the verdict — opinionated, slightly literary, with a soft modernity that prevents the system from reading "law firm." Inter is the prose — neutral, exceptionally legible at 11–13pt, and pairs cleanly with a serif without competing. Together: the almanac's voice (serif) and the almanac's pages (sans). Both fonts include real tabular lining figures, which lock dollar columns wherever money appears.

### Hierarchy

- **Display** (Fraunces 500, 38pt, line-height 1.05, letter-spacing -0.01em, `tnum lnum`): The headline balance on the Overview tab. The big "$4,287.40 on May 21." Used once or twice per screen, never more.
- **Headline** (Fraunces 500, 24pt, line-height 1.15, letter-spacing -0.005em, `tnum lnum`): Section titles ("Lowest point", "This week"), the verdict line in alerts ("You'll dip below your threshold on the 22nd").
- **Title** (Inter 600, 16pt, line-height 1.3): Sub-section titles, card headers, button labels, tab labels.
- **Body** (Inter 400, 13pt, line-height 1.5, `tnum lnum`): Default running text — table rows, helper copy, dialog body. Max line length 65–75ch where prose runs long (rare in this app).
- **Label** (Inter 500, 11pt, letter-spacing 0.06em, UPPERCASE): Tiny eyebrow labels above section blocks ("FORECAST WINDOW", "RECURRING"), table column headers, the legend strip under the chart. Floor for any visible text — never go smaller.

### Named Rules

**The Verdict Rule.** Fraunces is for the verdict — the headline number, the dated forecast claim, the section title that names the thing. It is never used for body text, helper copy, button labels, or table cells. Sans handles the support.

**The Tabular Numerals Rule.** Every number that represents money, a count, or a date renders in tabular lining figures. Enabled via `fontFeature: tnum, lnum` on display, headline, and body. Dollar columns in the transactions table must align to the decimal across rows; a number that wobbles by half a pixel between rows is a defect.

**The 11pt Floor Rule.** No visible text falls below 11pt. The Label role is the smallest legal size. This is an accessibility hard floor, enforced in `tests/test_accessibility.py`.

## 4. Elevation

This system is **flat by default.** Depth is conveyed through tonal layering on the paper-and-ink scale — `paper` / `paper-2` / `paper-3` in light, `ink-dark` / `ink-dark-2` / `ink-dark-3` in dark — and through 1px hairline rules in the `rule` token. Cards do not float. Tabs do not have drop shadows. The dashboard surface reads as a single warm sheet of paper with tonal regions, not a stack of floating panels.

Shadows exist for **one** purpose: surfaces that the OS itself would render with a shadow — popovers (the calendar date-picker), menus, dialogs. They are soft, low-elevation, hue-tinted, and used sparingly.

### Shadow Vocabulary

- **Popover** (`box-shadow: 0 4px 16px oklch(22% 0.015 30 / 0.10), 0 1px 2px oklch(22% 0.015 30 / 0.06)`): The calendar popover, dropdown menus, tooltip surfaces. Tinted ink, low blur radius, no Gaussian-blur stunts. In dark mode, swap the inner color to `oklch(0% 0 0 / 0.30)`.
- **Dialog** (`box-shadow: 0 12px 32px oklch(22% 0.015 30 / 0.14), 0 2px 6px oklch(22% 0.015 30 / 0.08)`): Confirm dialogs, the one-off transaction form. Slightly deeper than popover, still restrained.

### Named Rules

**The Flat-By-Default Rule.** No card, tab, banner, or row carries a shadow at rest. Elevation is tonal. If you find yourself reaching for `elevation=2` on a Flet `Card`, replace it with a `Container(bgcolor=paper_2, border=Border.all(1, rule))` — paper layering plus a hairline rule does the same job without lifting the surface.

**The No Inner Glow Rule.** No insets, no inner shadows, no faux-letterpress. The serif type already carries weight; chrome should not try to add more.

## 5. Components

Every component leads with a character line, then specifies the structural choices. Padding values reference the spacing scale (`sm`/`md`/`lg`); radii reference the rounded scale.

### Buttons

Buttons are typographic objects, not pill-shaped marketing surfaces. The radius is small (6px), the padding is comfortable but not bloated, and the label is Inter 600 in title size — never serif, never uppercase by default.

- **Shape:** 6px corner radius (`rounded.sm`). Never pill (`rounded.full`). Never square.
- **Primary:** Coral fill (`coral`), paper text (`paper`), Inter 600 / 16pt, padding 10px 18px. The only fully-saturated button in the system. One per screen at most.
- **Hover / Focus:** Background shifts to `coral-deep` on hover, 150ms ease-out. Focus state adds a 2px `coral-deep` ring offset by 2px from the button edge. No glow, no scale transform.
- **Ghost (default):** Transparent fill, `ink` text, Inter 600 / 16pt, padding 10px 14px. Hover fill is `paper-2` (light) or `ink-dark-2` (dark). This is the default everywhere except for the single primary CTA.
- **Icon-only buttons** must always be wrapped in `ft.Semantics(button=True, label="...")` — tooltips are not forwarded to screen readers on Flet desktop. The visible affordance is the tooltip on the inner IconButton; the accessible name is the Semantics label. Tested by `tests/test_accessibility.py` — do not relax the test.

### Chips

Used exclusively to tag recurring items with frequency or status ("biweekly", "monthly", "excluded"). Never decorative.

- **Style:** `paper-2` (light) / `ink-dark-2` (dark) background, `ink-2` text, 3px radius (`rounded.xs`), 2px × 6px padding.
- **State:** Selected state uses `coral-tint` fill with `coral-deep` text. Unselected stays neutral. There is no border.

### Cards / Containers

There is one card style — the **quiet card**. It is paper-on-paper, with a hairline rule, no shadow. Containers exist; cards-with-elevation do not.

- **Corner Style:** 10px radius (`rounded.md`).
- **Background:** `paper` in light, `ink-dark` in dark. Stepped to `paper-2` / `ink-dark-2` only when the card must visually separate from an already-paper background (e.g. a section card on a `paper` page).
- **Shadow Strategy:** None at rest. See Elevation section.
- **Border:** 1px solid `rule` / `rule-dark`. Always.
- **Internal Padding:** 20px vertical, 24px horizontal (`lg` × `xl`). Tighter cards (transaction row, alert banner) use 12px × 16px (`md` × `lg`).

**Nested cards are forbidden.** If you find yourself wanting a card inside a card, use a hairline rule and tonal layering instead.

### Inputs / Fields

Inputs are text-editor-like: paper background, single hairline border at rest, coral focus ring. No floating labels.

- **Style:** `paper` (light) / `ink-dark-2` (dark) fill, 1px `rule` border, 6px radius (`rounded.sm`), 10px × 12px padding, body type.
- **Label:** Real `label=` text, not placeholder-only. Sits above the field at Label size (Inter 500 / 11pt UPPERCASE).
- **Focus:** Border becomes 2px `coral`, fill stays paper. No glow, no shadow. The 2px width gives the focus state weight without animation.
- **Error:** Border becomes 2px `signal-negative`. Error message is `ft.Text` in `signal-negative` color, wrapped in `ft.Semantics(live_region=True, content=error_text)` so assistive tech announces it. Failing field receives focus.
- **Disabled:** Fill drops to `paper-2`, text to `ink-3`. No diagonal hatching.
- **Date fields** accept typed input via `_parse_date_input()` (formats: `YYYY-MM-DD`, `Jan 05, 2026`, `01/05/2026`). The adjacent calendar icon is for mouse users; keyboard users never have to open the popover.

### Navigation (Tab Strip)

The top-level dashboard navigation (Overview / Transactions / Adjustments) is a typographic tab strip, not a Material tab bar with a sliding underline.

- **Style:** Inter 600 / 16pt, 8px × 12px padding per tab.
- **Default:** `ink-3` text, transparent background.
- **Hover:** Text shifts to `ink-2`, background to `paper-2`.
- **Active:** Text becomes `coral`. A 2px `coral` underline sits 4px below the baseline of the active tab label. No background fill on the active tab — the color and underline are enough.
- **Keyboard:** `Cmd/Ctrl+1/2/3` jumps between tabs; switching focuses the first meaningful control of the new tab. New shortcuts go through `page.on_keyboard_event` in `src/main.py`, never per-view.

### Signature Component: The Forecast Chart

The chart is the product. Everything else is paper around it.

- **Surface:** Sits directly on the `paper` background. No card wrapper. No border. A 16px gutter on all sides; the chart owns its own breathing room.
- **Series:** A single 2px `coral` line for the projected balance. No fill underneath at rest. Reduce-motion users see straight segments; everyone else gets a smooth spline.
- **Threshold:** A 1px dashed `signal-threshold` (amber) horizontal line at the user's safety threshold, with a small label at the right edge ("Threshold $500"). Threshold-crossing markers are 6px `signal-threshold` filled circles at the exact crossing date, plus a vertical 1px dashed `signal-threshold` tick down to the date axis.
- **Axes:** `rule` color, 1px solid. Tick labels in `ink-3`, Label size, tabular numerals.
- **Today marker:** A 1px solid `paper-3` vertical band (`ink-dark-3` in dark) running the full chart height at today's date, sitting behind the data line. Subtle — a column of slightly warmer paper.
- **Tooltip:** On hover, a `paper` floating tile with a `rule` border, 6px radius, popover shadow. Date in Headline (Fraunces 500), balance in Display tabular figures, delta on its own line below in signal-positive or signal-negative.
- **Accessible alternative:** The Transactions tab is the text equivalent. Any change to what the chart conveys must update `build_forecast_chart_summary()` in `src/views/chart.py`, which produces the text the chart's `ft.Semantics(label=...)` wrapper announces to screen readers.

## 6. Do's and Don'ts

### Do:

- **Do use OKLCH** as the canonical color reference; the frontmatter ships sRGB hex approximations because Flet consumes hex, but new tokens are designed in OKLCH first.
- **Do tint every neutral toward hue 30** at chroma 0.005–0.015. Untinted gray is forbidden. So is `#fff` and `#000`.
- **Do enable tabular lining figures** on every text role that may contain numbers — `display`, `headline`, `body`. Use `fontFeature: "tnum, lnum"` or Flet's text style equivalent.
- **Do wrap every icon-only button** in `ft.Semantics(button=True, label="...")` with a descriptive, per-row label ("Edit one-off Rent", not "Edit"). The accessibility regression test depends on it.
- **Do design light and dark as equals.** Every token has a dark-mode counterpart on the paper-dark/ink-dark scale. No second-class theme.
- **Do reserve color for meaning.** Coral = brand. Green = surplus. Red = shortfall. Amber = threshold. If a color is decorative, remove it.
- **Do use tonal layering and hairlines for depth.** Replace any reflex `elevation=2` with `paper-2` background + `rule` border.
- **Do honor reduce-motion.** Read `DashboardView._reduce_motion` and pass it through to any animated element. The chart already does this; new motion-bearing components must accept the same flag.

### Don't:

- **Don't ship the current Material defaults.** `color_scheme_seed=Colors.BLUE`, default elevation, default Material card chrome — PRODUCT.md calls this out as the anti-reference and the explicit reason this design system exists. Replace it with the warm-neutral scale and coral accent.
- **Don't fall into the crypto / fintech-bro aesthetic.** No neon-on-black, no gradient text, no `background-clip: text` tricks, no animated number tickers, no glassmorphism, no "to the moon" energy. Money is serious.
- **Don't fall into cluttered SaaS dashboard tropes.** No identical card grids. No hero-metric template (big number + tiny label + gradient accent). No side-stripe `border-left: 4px solid` accents on alerts. No modal-as-first-thought — exhaust inline progressive disclosure first.
- **Don't fall into Mint-style busy budgeting UI.** No pie charts. No category-explorer bait. No gamification badges. No marketing-style upsells inside the app.
- **Don't use `ft.Colors.OUTLINE` for text.** It is a borders-and-hairlines token. Secondary text uses `ON_SURFACE_VARIANT` (mapped to `ink-2`) — enforced by convention in CLAUDE.md.
- **Don't drop below 11pt** for any visible text. The Label role is the floor. Nav rail labels at 8–10pt were the previous regression — do not return there.
- **Don't substitute color for label.** Every red/green/amber signal pairs with a glyph (`+`, `−`, ⚠), a `semantics_label`, or text. Color-blind users must still read the forecast.
- **Don't shadow flat surfaces.** Cards, tabs, banners, rows do not float. Only popovers, menus, and dialogs shadow.
- **Don't nest cards.** If a card wants a child card, use a hairline rule and `paper-2` instead.
- **Don't render currency in proportional figures.** Every dollar amount uses tabular lining figures so columns lock.
- **Don't add scroll choreography or entrance animations.** The "will I be okay?" glance must not wait on an animation. State changes only.
- **Don't use em dashes** in UI copy. Commas, colons, semicolons, periods, or parentheses. (PRODUCT.md inherits this rule from the impeccable shared design laws.)
