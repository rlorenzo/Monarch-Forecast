# Changelog

All notable changes to Monarch Forecast are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-05-16

Monarch Forecast is a desktop app that projects your checking account
balance day-by-day, so you can see what you'll have on hand a few weeks
out, before bills hit, paychecks land, or recurring charges sneak up
on you. It reads your existing Monarch Money account; you don't
re-enter data.

### What's in 1.0

- **Day-by-day balance forecast.** See your projected checking balance
  for every upcoming day, not just an end-of-month estimate. The
  forecast updates as your real transactions come in.
- **Automatic recurring detection.** The app spots your recurring
  income and bills from the last 90 days of activity, so you don't
  have to tag or categorize anything manually.
- **What-if adjustments.** Add a one-off transaction, override a
  recurring amount, or temporarily exclude an item to see how the
  forecast shifts. Useful for "what if I move this rent payment a
  week" or "what if I skip this subscription".
- **Credit-card payment estimation.** Projects the next statement
  balance and payment date for each card so a large autopay doesn't
  catch you by surprise.
- **Low-balance alerts.** Flags any upcoming day your projected
  balance drops below a threshold you set.
- **Demo mode.** Try the full app on realistic synthetic data without
  connecting an account. Storage is isolated, so it can't touch any
  real data.

### Privacy and security

- Runs entirely on your machine. Credentials live in your OS keychain;
  transaction data is cached locally in `~/.monarch-forecast/`.
- Session and cache files are written with restricted permissions and
  refuse to read symlinks or files owned by another user.
- No telemetry. The app only talks to Monarch Money's API and to
  GitHub (for update checks).

### Supported platforms

macOS (Intel and Apple Silicon), Windows, and Linux desktop builds
are attached below.

## [0.1.0-alpha.1] — 2026-04-07

Initial alpha release. Cash-flow forecasting for Monarch Money checking
accounts, with recurring-transaction detection, credit-card payment
estimation, low-balance alerts, manual one-off adjustments, and cross-platform
desktop builds (macOS / Windows / Linux).

[Unreleased]: https://github.com/rlorenzo/Monarch-Forecast/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rlorenzo/Monarch-Forecast/compare/v0.1.0-alpha.1...v1.0.0
[0.1.0-alpha.1]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v0.1.0-alpha.1
