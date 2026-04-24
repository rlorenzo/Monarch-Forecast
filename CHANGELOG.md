# Changelog

All notable changes to Monarch Forecast are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Security scanning: bandit runs in pre-commit at medium+ severity; semgrep
  runs in CI with the `p/python`, `p/security-audit`, and `p/owasp-top-ten`
  rule packs.
- `SECURITY.md` describing the private vulnerability reporting process.
- `CONTRIBUTING.md` documenting the contribution, testing, and code-style
  policy.

### Changed

- Hardened on-disk secret handling: session and cache files are created with
  `0600` permissions atomically (no pre-`chmod` read window), reject symlinks
  and non-regular files, and verify current-user ownership on open.
- Flipped `src.data` and `src.forecast` layering so the forecast engine sits
  above raw data fetching; enforced via `tach`.

### Fixed

- Skip update check when running without installed package metadata
  (avoids spurious "update available" banners from source checkouts).
- Honor credit-card amount overrides when the billing cycle has no charges.
- Avoid empty-`Semantics` dismiss state; tolerate corrupt one-off amounts.
- Accurate chart summary start balance; alerts live-region sync.

## [0.1.0-alpha.1] — 2026-04-07

Initial alpha release. Cash-flow forecasting for Monarch Money checking
accounts, with recurring-transaction detection, credit-card payment
estimation, low-balance alerts, manual one-off adjustments, and cross-platform
desktop builds (macOS / Windows / Linux).

[Unreleased]: https://github.com/rlorenzo/Monarch-Forecast/compare/v0.1.0-alpha.1...HEAD
[0.1.0-alpha.1]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v0.1.0-alpha.1
