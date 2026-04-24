# Contributing

Thanks for your interest in contributing. Contributions of bug reports,
features, documentation, and tests are welcome.

## Reporting bugs and requesting features

Open an issue at [GitHub Issues](https://github.com/rlorenzo/Monarch-Forecast/issues)
and include:

- What you expected to happen and what actually happened.
- Steps to reproduce.
- Your operating system and how you installed the project.
- Relevant log output, if any.

For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead — do
not open a public issue.

## Submitting changes

1. Open an issue before investing significant time, so we can agree on scope
   and approach.
2. Fork the repository and create a branch from `main`.
3. Set up your development environment — see the
   [Development](README.md#development) section of the README.
4. Install the pre-commit hooks: `uv run pre-commit install`. They mirror the
   checks CI runs.
5. Make your change, including tests (see below).
6. Open a pull request against `main`. All CI checks must pass.

## Testing

Pull requests that change behavior should include tests. Bug fixes should
include a regression test that fails without the fix.

- Unit tests live in [tests/](tests/); mirror the source layout.
- Mock external boundaries (network, OS keychain, third-party clients).
- Prefer fixtures over shared mutable state.

## Code style

- Linting and type checking are enforced in CI and pre-commit. Fix all
  findings before submitting.
- Run the formatter before committing.
- Keep public APIs documented and typed.

## Commit messages

- Use clear, imperative commit messages ("add X", "fix Y", not "added"
  / "fixes").
- Reference issues or PRs where relevant.
- Keep unrelated changes in separate commits.
