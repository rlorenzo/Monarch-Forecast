# Security Policy

We take security issues seriously and appreciate responsible disclosure. Thank
you for helping keep this project and its users safe.

## Reporting a vulnerability

**Please do not report vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Report privately via GitHub's private vulnerability reporting:

> [Report a vulnerability](https://github.com/rlorenzo/Monarch-Forecast/security/advisories/new)

If you cannot use GitHub, email `rexlorenzo@gmail.com` with the subject line
`[Monarch Forecast Security]`.

Please include:

- A description of the issue and its potential impact.
- Steps to reproduce, ideally with a minimal proof of concept.
- The affected version (git commit SHA or release tag).
- Your operating system and runtime details, if relevant.
- Whether you would like to be credited in the release notes.

## What to expect

- **Initial response within 14 days** acknowledging the report.
- Regular status updates as the investigation progresses.
- Coordinated disclosure: we will agree on a timeline with you before any
  public discussion of the issue.

## Scope

Monarch Forecast is a desktop application that handles financial account
credentials and session data. In scope:

- **Credential handling** — storage and retrieval of Monarch Money credentials
  via `keyring` and the OS keychain.
- **Local data files** — the session pickle, SQLite cache, and preferences
  file under `~/.monarch-forecast/`, including file permissions and symlink
  handling.
- **Network communication** — traffic to Monarch Money's servers and the
  GitHub Releases API.
- **Release artifact integrity** — the installers published on
  [GitHub Releases](https://github.com/rlorenzo/Monarch-Forecast/releases).

Out of scope:

- Vulnerabilities in Monarch Money's backend or API.
- Vulnerabilities in third-party dependencies already disclosed upstream —
  please report those to the relevant project. We will update once an
  upstream fix ships.
- Issues that require the attacker to already have local code execution or
  filesystem write access as the running user.

## Supported versions

Only the latest release receives security updates. Please upgrade before
reporting.
