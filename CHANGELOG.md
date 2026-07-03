# Changelog

All notable changes to Monarch Forecast are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] (2026-07-02)

A forecast-accuracy release: recurring detection is rebuilt around a
two-year window, credit card estimates net out refunds, and the
Transactions tab gains Recent and Both ledgers.

### Added

- **Recent and Both ledgers.** The Transactions tab now has three
  modes (pills; Cmd/Ctrl+4 cycles). Recent shows the checking
  account's completed transactions (7/30/90 days, search, flow
  filters); Both stacks projected and completed activity into one
  ledger split by a TODAY divider.
- **Recurring detection across two years.** A 750-day lookback
  (backed by a new incremental cache) detects bimonthly through
  yearly cadences. Median-based intervals tolerate missed or split
  charges, stale streams stop projecting, and penalty fees and bare
  descriptors ("Deposit", "ATM") are never projected.

### Fixed

- **Credit card estimates:** refunds and statement credits net into
  the estimate, due days come from the card's own payment history,
  due-today payments stay in the forecast, early payments no longer
  double-count, and partial payments bill the unpaid remainder.
- **Name collisions:** recurring card-payment stripping is tightly
  scoped, so a Chase mortgage survives a "Chase Reserve" card.
- **Inputs:** the recurring override parses "\$2,500.00" and shows
  an error instead of silently deleting; it and the safety threshold
  commit on blur; non-finite amounts and past dates are rejected.
- **Guards and robustness:** Cmd/Ctrl+R and account switches honor
  unsaved card edits; preferences saves are atomic and
  symlink-hardened; null account fields no longer crash the load.
- **Contrast:** colour tokens retuned to clear WCAG AA at the small
  sizes money columns actually render at.

### Security

- msgpack 1.2.1 (fixes GHSA-6v7p-g79w-8964, high severity),
  aiohttp 3.14.1, cryptography 48.0.1.

### Internal

- Least-privilege, SHA-pinned release CI; jscpd copy-paste gate;
  Python 3.12 and Node pins; commit hook strips AI session trailers.

## [1.0.3] (2026-05-25)

A small UX release focused on making the left-rail refresh timestamp
honest about staleness, plus the project's adoption of `AGENTS.md` as
the cross-tool source of truth for AI coding assistant conventions.

### Changed

- **Last-refresh label now reads as a relative time.** The nav rail
  used to show `Updated 4:30 PM` with no date attached, so a forecast
  loaded yesterday and a forecast loaded an hour ago looked
  identical. The label now renders as `Just now`, `5 min ago`,
  `Today, 4:30 PM`, `Yesterday, 5:00 PM`, `3 days ago`, or a full
  date for older data. A 60s tick keeps the label current without
  re-loading data.
- **Stale data is flagged in three ways.** Once the underlying
  forecast is more than 12 hours old the label gains a leading ⚠
  glyph, a tooltip with the full string (so users with scaled fonts
  recover what the rail ellipsizes), and a screen-reader
  announcement that adds "(stale)" after the timestamp. Colour alone
  was considered and rejected: the `SIGNAL_THRESHOLD` amber sits at
  ~2.14:1 on `PAPER`, below the WCAG AA bar for small text.

### Internal

- Project conventions moved from `CLAUDE.md` to `AGENTS.md`. The
  former is now a two-line pointer so Claude Code's auto-load by
  filename keeps working; Cursor, Codex, and Antigravity pick up the
  new file natively.
- `uv.lock` is bumped alongside `pyproject.toml` on version bumps
  (the 1.0.2 release missed this and the lockfile drifted). Captured
  as a convention in `AGENTS.md`.

## [1.0.2] (2026-05-19)

A small release focused on making demo mode actually demonstrate what
the app is for: spotting upcoming shortfalls before they happen.

### Changed

- **Demo mode now shows a real deficit.** The synthetic checking
  balance starts at a tighter \$720 and seeds three upcoming one-off
  bills (auto insurance, dentist visit, DMV renewal) anchored to days
  ahead of today, so the 45-day forecast always dips below zero for a
  few days before the next paycheck rescues it. Previously the demo
  forecast never went negative, which buried the low-balance and
  overdraft alerts that are the whole point of the tool.
- **Demo cache is wiped on every launch.** Edits to the synthetic data
  are no longer shadowed by a stale 30-minute cache entry, so the demo
  reflects the current code immediately.

### Internal

- README has a real Screenshots section with Overview, Transactions,
  and Adjustments captures from the new demo (lossless-compressed).
- Em dashes removed from every markdown doc in the repo.

## [1.0.1] (2026-05-18)

A patch release that fixes a critical launch crash and adds OS
password-manager support to the sign-in screen. **Anyone running 1.0.0
should upgrade**: the previous build did not start at all on a clean
install.

### Fixed

- **App now starts.** 1.0.0 silently exited within a fraction of a
  second of launch on every platform: the window briefly appeared and
  then closed with no error message. The packaged entry point imported
  the Flet runtime but never started it. Reinstall to apply.

### Added

- **Sign-in autofill.** macOS Keychain, 1Password, Bitwarden, and other
  OS password managers can now fill the Email and Password fields and
  offer to save credentials after a successful sign-in. The save prompt
  only appears when "Remember credentials" is checked, mirroring the
  existing keychain behavior. One-time MFA codes are recognised as
  one-time codes (not stored).

### Changed

- The Safety Threshold help dialog is now a single Markdown block:
  same content, cleaner typography for the bulleted list.

### Internal

- Desktop release builds now run a launch + render smoke test before
  the artifact is uploaded. A binary that exits in under 12 seconds or
  opens a blank window fails the build instead of silently shipping
  (which is how 1.0.0 escaped review).

## [1.0.0] (2026-05-16)

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

[Unreleased]: https://github.com/rlorenzo/Monarch-Forecast/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.1.0
[1.0.3]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.3
[1.0.2]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.2
[1.0.1]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.1
[1.0.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.0
