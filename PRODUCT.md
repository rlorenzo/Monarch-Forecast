# Product

## Register

product

## Users

A Monarch Money subscriber on their personal desktop — financially engaged enough to pay for Monarch, but not a professional analyst. Almost always solo, usually checking the app for a few seconds at a time ("will I be okay this week?"), occasionally sitting down for a longer planning session ("what's hitting in the next 45 days?").

The job to be done is **deciding before doing**: can I afford this purchase, when is the next risky window, do I need to move money around. Monarch shows what already happened; this app projects what's coming next. Success looks like the user opening the app before a financial decision and getting a confident yes/no in under two seconds.

## Product Purpose

Monarch Forecast projects a checking account balance day-by-day for the next 45+ days by combining detected recurring income/expenses, credit card payment estimates, and user-entered one-offs. It exists because Monarch Money does not surface forward-looking cash flow at all — the projection has to be reconstructed by hand from a dozen scattered signals. This app does it automatically, surfaces shortfalls, and lets the user nudge the forecast with one-off transactions and exclusions.

It is a single-screen desktop app: one chart, one threshold line, three tabs (Overview, Transactions, Adjustments). It is not a budgeting app, not a categorization tool, not a financial advisor.

## Brand Personality

**Confident. Warm. Direct.**

The voice of a friend who happens to be good with money: opinionated about defaults, honest about uncertainty, allergic to hedging copy. Closer to Monzo or Copilot than to a bank — willing to render a verdict ("you'll dip below your threshold on the 22nd") rather than dumping numbers and letting the user solve them.

The interface should feel **calm and considered**, not clinical. Numbers are first-class, but rhythm and spacing keep it from feeling like a Bloomberg terminal. Color is reserved for meaning — green/red for direction, a single signal hue for the threshold crossing — never for decoration.

## Anti-references

Explicitly NOT:

- **Stock Material defaults.** The current app uses `color_scheme_seed=Colors.BLUE` and otherwise inherits Material 3's defaults. It reads as "an unfinished Flutter app," not a considered product. Branded surface, opinionated chart, deliberate type scale — required.
- **Crypto / fintech-bro aesthetic.** No neon-on-black, no gradient text, no animated number tickers, no glassmorphism, no "to the moon" energy. Money is serious; the chrome should be quiet.
- **Cluttered SaaS dashboard tropes.** No identical card grids, no hero-metric template (big number + tiny label + gradient accent), no side-stripe alerts, no modal-as-first-thought. Inline progressive disclosure beats a popover every time.
- **Mint-style busy budgeting UI.** No pie charts, no category-explorer bait, no gamification, no marketing-style upsells.

## Design Principles

1. **The chart answers first.** A repeat-glance user must see the balance trajectory and any shortfall markers within two seconds of the app focus event. No skeleton-then-data-then-chrome cascade for the primary surface. The chart and its alerts banner are the product; everything else is support.
2. **Calm, not clinical.** This is personal finance, not a trading floor. Numbers stay precise, but typographic rhythm, generous-enough spacing, and slightly warm neutrals keep the surface from feeling cold or bank-like.
3. **Color carries meaning, never decoration.** Green and red signal direction (above/below threshold, surplus/deficit). The threshold crossing has its own dedicated hue. Everything else — chrome, chart axes, table cells — sits in tinted neutrals. If color is used and it isn't telling the user something, remove it.
4. **Opinionated defaults, frictionless escape hatches.** The app makes calls: which recurring items count, which credit cards get estimated, what the safety threshold is. Defaults are confident and visible; overrides are one click away. No settings-page tax for everyday adjustments.
5. **Density without claustrophobia.** The Transactions tab is dense by design (it's the text equivalent of the chart for screen-reader users and the planning view for everyone else). Rhythm — varied row heights, intentional whitespace between sections — keeps density readable instead of suffocating.

## Accessibility & Inclusion

The app already ships with a thorough accessibility contract documented in `CLAUDE.md` and `README.md`. Treat that as a hard floor — any UI work must preserve or improve it:

- **Screen readers**: VoiceOver (macOS) is the primary tested target; Narrator (Windows) for buttons and forms. Every icon-only button is wrapped in `ft.Semantics(button=True, label=...)`; tooltips are not enough.
- **Keyboard-only**: Tab/Shift+Tab navigation, Escape closes dialogs, global shortcuts (⌘R refresh, ⌘1/2/3 tabs). All new shortcuts go through `page.on_keyboard_event` in `src/main.py`.
- **Text scaling**: Material icon theme honors OS text size. Minimum body text size is 11pt.
- **Reduce motion**: The balance chart respects the OS reduce-motion flag (straight segments instead of curved spline). New animations must take a `reduce_motion` kwarg.
- **High-contrast & color blindness**: Color is never the sole carrier of meaning — pair every red/green signal with a `+`/`−` sign, a `semantics_label`, or text. Secondary text uses `ON_SURFACE_VARIANT`, never `OUTLINE`.
- **Alternative to the chart**: The Transactions tab is a complete text equivalent. Any chart change that introduces new information must also update `build_forecast_chart_summary()` so the screen-reader summary stays accurate.

WCAG target is AA across both light and dark themes. The regression suite at `tests/test_accessibility.py` enforces the icon-button-labeling rule — when it fails, fix the wrapper, not the test.
