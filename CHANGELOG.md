# Changelog

All notable changes to Monarch Forecast are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-05-16

First stable release. The app moves from the initial alpha to a
production-quality build with a redesigned interface, hardened security
posture, and a thorough test suite.

### Added

- **Editorial "paper and ink" design system.** Warm clay-toned neutrals,
  coral brand accent, Fraunces display serif paired with Inter, tabular
  lining figures for all money columns, and a documented token set in
  `src/views/tokens.py`. The system is described in `DESIGN.md`.
- **Editorial left-hand nav** with a paper-and-ink wordmark, chart-in-paper
  logo seal, and coral selection rail. Replaces the previous Material
  `NavigationRail`.
- **Editorial Overview tab** centred on a Fraunces verdict block ("$X on
  Thu, May 21") plus a starting / net / ending ledger. Stock Material
  summary cards are gone.
- **Editorial day-block Transactions ledger** with a serif date gutter,
  per-day net summary, true-minus signed amounts, and a search + filter
  chip strip that keeps focus across forecast rebuilds.
- **Editorial Adjustments tab** with collapsible Credit Cards section
  (collapsed by default), inline one-off form with mini-ledger, and
  recurring rows showing detected items with frequency pills, signal
  arrows, override fields (coral border + strike-through when active),
  and a meta chip showing inclusion count.
- **Security scanning:** `bandit` runs in pre-commit at medium+ severity;
  `semgrep` runs in CI with the `p/python`, `p/security-audit`, and
  `p/owasp-top-ten` rule packs.
- `SECURITY.md` describing the private vulnerability reporting process.
- `CONTRIBUTING.md` documenting the contribution, testing, and
  code-style policy.
- ~390 new unit tests bringing total coverage from 57% to 95%. New
  suites cover the Adjustments panel and dialogs, dashboard handlers
  and lifecycle, calendar popover, login flow, updater HTTP, monarch
  client, recurring detector, alerts dismiss flow, transactions view,
  CC billing card validation, and the global keyboard dispatcher.

### Changed

- **Tab focus on switch.** `Cmd/Ctrl+1/2/3` focuses the first meaningful
  control of the destination tab (account dropdown, search field, or
  one-off description field) instead of leaving keyboard focus on the
  nav rail.
- **CC checkbox vs row toggle.** The Credit Cards section header is
  click-to-expand, but the checkbox cell now carries a no-op `on_click`
  absorber so toggling include/exclude doesn't bubble to the row's
  expand/collapse.
- **CC section re-renders on inclusion toggle and amount edit.** The
  meta chip count and per-card colours stay in sync without a tab
  switch, guarded so an in-flight edit on another card doesn't lose
  its dirty state.
- **One-off validation.** The inline form now rejects amounts ≤ 0 with
  the same copy as the dialogs.
- **`account_dropdown.update()` swapped to `_safe_update`** in
  `load_data`, so unmounted callers (tests, hot-reload races) don't
  crash.
- **Hardened on-disk secret handling:** session and cache files are
  created with `0600` permissions atomically (no pre-`chmod` read
  window), reject symlinks and non-regular files, and verify
  current-user ownership on open.
- **Module layering:** flipped `src.data` and `src.forecast` so the
  forecast engine sits above raw data fetching; enforced via `tach`.
- **`dispatch_keyboard_shortcut` extracted from `main`** as a
  module-level pure function so the routing logic is unit-testable.

### Removed

- Three dead summary-card builder methods from `dashboard.py`
  (`_balance_trajectory_card`, `_cash_flow_card`, `_summary_card`)
  superseded by the editorial verdict block.

### Fixed

- Skip update check when running without installed package metadata
  (avoids spurious "update available" banners from source checkouts).
- Honor credit-card amount overrides when the billing cycle has no
  charges.
- Avoid empty-`Semantics` dismiss state; tolerate corrupt one-off
  amounts.
- Accurate chart summary start balance; alerts live-region sync.

## [0.1.0-alpha.1] — 2026-04-07

Initial alpha release. Cash-flow forecasting for Monarch Money checking
accounts, with recurring-transaction detection, credit-card payment
estimation, low-balance alerts, manual one-off adjustments, and cross-platform
desktop builds (macOS / Windows / Linux).

[Unreleased]: https://github.com/rlorenzo/Monarch-Forecast/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rlorenzo/Monarch-Forecast/compare/v0.1.0-alpha.1...v1.0.0
[0.1.0-alpha.1]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v0.1.0-alpha.1
