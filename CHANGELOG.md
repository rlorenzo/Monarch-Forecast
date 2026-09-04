# Changelog

All notable changes to Monarch Forecast are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Sign In no longer lets the Monarch library load a stale `session.pickle`
  behind the app's own ownership and permission checks.
- Logging out now clears the transaction cache (`cache.db`), not just the
  keychain credentials and session file.
- The macOS build drops the `allow-dyld-environment-variables` entitlement,
  which let a local process inject code into the signed app and read the
  stored password from the Keychain without a prompt.
- "Remember credentials" is now off by default.
- Data-loading errors show a generic message instead of the raw exception
  text, which could include request URLs and server responses.
- `requirements.txt` now requires the same `monarchmoneycommunity` floor as
  `pyproject.toml`, the version that stops persisting short-lived tokens.
- CI and release builds pin `semgrep` (via `uv.lock`) and `create-dmg`
  (release tarball with SHA-256 check) instead of installing whatever is
  current.
- Preferences are opened with `O_NOFOLLOW` on read, matching the write path.

## [1.4.0] (2026-08-14)

The Transactions tab now reads oldest first by default, and Upcoming, Recent,
and Both share one sort order. Click the DATE column header to flip it.

### Added

- Sort order for the Transactions tab, set from the DATE column header and
  remembered between launches.

### Changed

- Upcoming, Recent, and Both now share one sort direction instead of each
  keeping its own, so switching modes no longer reverses the timeline. In Both
  mode the two halves swap sides with the order, keeping the TODAY line
  mid-timeline.
- `monarchmoneycommunity` 1.5.1 → 1.5.2. Additive only; no behavior change.

### Fixed

- The "showing the N most recent transactions" note in the Recent ledger now
  sits at the end the dropped rows were cut from, rather than always the
  bottom.
- The DATE column header's hover highlight never rendered.

### Security

- Security fixes in bundled dependencies: `aiohttp` 3.14.1 → 3.14.3
  (CVE-2026-69244, CVE-2026-69243, CVE-2026-59881) and `cryptography`
  48.0.1 → 50.0.0 (CVE-2026-69247; affects Linux only). Development-only
  dependencies were updated as well.

## [1.3.1] (2026-07-19)

Packaging improvements for Windows and Linux — no application changes.

### Changed

- **Windows now ships an installer** (`monarch-forecast-windows-setup.exe`): a
  per-user install (no admin) with a Start Menu shortcut and an uninstaller,
  replacing the portable zip.
- **Linux now ships a real `.AppImage`** instead of a tarball — make it
  executable and run it (needs FUSE / `libfuse2`).

### Fixed

- Corrected the README and build docs, which mislabeled the Windows download as
  a `.msix` and the Linux download as an `.AppImage`.

## [1.3.0] (2026-07-19)

macOS builds are now code-signed and notarized by Apple and ship in a styled
installer window, so the app opens without any Gatekeeper warning.

### Added

- **Signed and notarized macOS builds.** The `.dmg` is signed with a
  Developer ID certificate, notarized by Apple, and stapled, so it opens
  with no "app is damaged" prompt or right-click-to-open workaround. The
  signing pipeline lives in `packaging/macos/` and runs in CI on every
  macOS build.
- **Styled DMG installer.** The disk image opens to a designed window — a
  paper background, the Fraunces wordmark, and a drag-to-Applications
  prompt — instead of a bare file listing.

### Changed

- **Smaller downloads on every platform.** The build was bundling the whole
  project directory into the app, including the multi-megabyte virtualenv,
  git history, and test suite. Those are now excluded, shrinking the bundled
  app payload from ~54 MB to under 1 MB (and, on macOS, removing the unsigned
  binaries that had blocked notarization).

### Internal

- **CI actions updated to their Node 24 releases** (checkout, setup-python,
  setup-node, upload/download-artifact, setup-uv, ruff-action,
  action-gh-release), still SHA-pinned, ahead of GitHub's Node 20 removal.

## [1.2.0] (2026-07-18)

A correctness release: credit card statement estimates now track the
statement the issuer actually billed, alongside a vetted dependency
refresh.

### Fixed

- **Credit card estimates anchor on the balance at statement close.**
  Estimates summed charges by transaction date, but issuers bill by
  post date, so a charge posting just after a close was counted on the
  wrong statement (one real card forecast ran ~40% low). The estimate
  is now the account balance rolled back to the close date, keeping
  every charge on the statement it was billed to. A card carrying a
  negative balance now always forecasts a payment at its next due
  date, since the balance itself is the evidence.

### Internal

- **Dependencies refreshed.** Runtime: monarchmoneycommunity 1.3.2 to
  1.5.1 (clearer login failures on bad MFA codes), Flet 0.85.1 to
  0.85.3. Dev tooling: ruff 0.15.21, ty 0.0.58, pytest 9.1.1,
  pytest-asyncio 1.4.0. Every bump cleared a 7-day publish-age check
  and carries no known security advisories.

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

[Unreleased]: https://github.com/rlorenzo/Monarch-Forecast/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.4.0
[1.3.1]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.3.1
[1.3.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.3.0
[1.2.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.2.0
[1.1.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.1.0
[1.0.3]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.3
[1.0.2]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.2
[1.0.1]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.1
[1.0.0]: https://github.com/rlorenzo/Monarch-Forecast/releases/tag/v1.0.0
