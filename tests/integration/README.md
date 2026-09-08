# Flet integration tests

These drive the **real rendered app** through a Flutter test host, unlike the
suite in `tests/`, which asserts on control trees. They are excluded from the
default `pytest` run (`addopts` in `pyproject.toml`) because they need a host
provisioned by `flet test`.

## Running

```bash
uv sync --group integration
uv run flet test macos . \
  --project "Monarch Forecast" \
  --org "com.monarchforecast" \
  --product "Monarch Forecast" \
  --tests-dir tests/integration \
  --exclude .venv .git .github .boost .pytest_cache .ruff_cache .impeccable \
            build monarch_forecast.egg-info screenshots design web packaging \
  --skip-flutter-doctor
```

Run it from an **interactive terminal session**. The Flutter host has to open a
real window; launched from a non-GUI context it starts, never connects, and the
first `pump_and_settle` times out after ~11 minutes with no other diagnostic.

## Four things that cost an afternoon to discover

1. **Argument order is `flet test <platform> <app_path> --tests-dir <dir>`.**
   `flet test tests/integration` fails with `invalid choice` because the first
   positional is the platform.
2. **App metadata must be passed as flags.** This repo has no `[tool.flet]`
   section — `build.yml` passes `--project` / `--org` / `--product` on the
   command line, and `flet test` needs the same.
3. **`.boost` must be excluded.** Packaging copies the project directory, hits
   the Unix socket at `.boost/graph/daemon.sock`, and dies with
   `FileSystemException ... errno = 45` (`ENOTSUP`). **That error is invisible
   without `-v`** — the packaging subprocess output is captured unless
   `verbose >= 1`, so all you see is "Flet app package was not staged to
   build/python-app." Any socket or FIFO in the tree will do the same.
4. **`flet.testing` has undeclared dependencies.** It imports `numpy`, `PIL`,
   and `skimage.metrics` for screenshot comparison; Flet declares none of them.
   Hence the `integration` dependency group.

## What this unlocks

`FletTestApp` offers `resize_page(width, height)` and
`assert_control_screenshot(name, control, similarity_threshold=...)`, with
`FLET_TEST_GOLDEN=1` (or `--update-goldens`) to capture baselines.

That is the tooling for the ledger clipping defect: `min_width = 900` while the
ledger needs 1102 px, so the BALANCE column is cut off between those widths with
no horizontal scroll. A control-tree assertion cannot catch it; a screenshot at
each boundary width can.
