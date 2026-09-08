# Flet integration tests — why this directory has no tests

Flet 0.86 ships `flet.testing`: a Flutter-driver-style harness with finders,
real tap/type/drag, `resize_page`, and screenshot comparison. It looked like
the answer to the gap that let the ledger clipping bug survive 800+ tests —
none of which render.

**It does not currently work for this app.** The harness targets mobile. What
follows is what was tried, so the next person spends minutes rather than an
afternoon.

## The two modes, and why both are dead ends here

`flet/pytest_plugin.py::_is_device_mode` picks between them.

### Device mode (the default for `flet test`)

The packaged app runs for real and a `RemoteTester` drives it over a socket.
This part genuinely works: the app builds, launches, renders, loads fonts, and
the tester connects. But for testing this app it gives nothing to assert on:

- **`flet_app.page` raises `RuntimeError: page is not initialized`.** There is
  no Python-side `Page` — the app owns it on the far side of the socket. So
  `assert_control_screenshot`, which starts with `self.page.clean()`, cannot
  run at all.
- **`take_screenshot` raises `Full app screenshots are only available on
  Android and iOS.`** No macOS goldens, full stop.
- **Finders return `count=0`** for every probe against this app's login screen
  (`Demo`, `Sign`, `Email`, `Password`, `Monarch`, `Forecast`, `Overview`),
  after pumping 6s.
- **`flet_app_main` is ignored.** It is only consulted when *not* in device
  mode, so a fixture that passes a custom `main` silently tests the packaged
  app instead. The tell is `setWindowMinSize(900.0, 600.0)` in the verbose log
  — that is `src/main.py`, not your fixture.

### Host mode (`FLET_TEST_DEVICE_MODE=0`)

Python drives the page in-process, so `page` exists and `flet_app_main` is
honoured. It needs three more things — and then still fails:

- `FLET_TEST_FLUTTER_APP_DIR` pointing at a provisioned host.
- `FLET_TEST_DISABLE_FVM=1`, or it shells out to `fvm` and dies with
  `FileNotFoundError: 'fvm'`.
- A Flutter test target **built for host mode**, which is the blocker. Host
  mode passes `--dart-define=FLET_TEST_APP_URL`, while the target `flet test`
  provisions into `build/flutter` is a device-mode one that demands
  `FLET_TEST_SERVER_URL` and throws
  `Exception: FLET_TEST_SERVER_URL dart-define is required.`
  Flet's own repo builds a host-mode target for its internal tests; `flet test`
  does not produce one.

## Other things that cost time

- **Argument order is `flet test <platform> <app_path> --tests-dir <dir>`.**
  `flet test tests/integration` fails with `invalid choice` — the first
  positional is the platform.
- **App metadata must be flags.** This repo has no `[tool.flet]` section;
  `build.yml` passes `--project` / `--org` / `--product` and `flet test` needs
  the same.
- **`.boost` must be excluded.** Packaging copies the project directory, hits
  the Unix socket at `.boost/graph/daemon.sock`, and dies with
  `FileSystemException ... errno = 45` (`ENOTSUP`).
- **`flet.testing` has undeclared dependencies** — `numpy`, `PIL`,
  `skimage.metrics`. Hence the `integration` dependency group.
- **`pump_and_settle` never returns.** The login screen carries an
  indeterminate `ProgressBar`, which animates forever, so there is never a
  quiet frame; it times out after ~10 minutes. `skip_pump_and_settle: True`
  plus explicit `pump()` calls avoids it. This one alone turned a 33-second
  run into a 10m37s one.

**Pass `-v`.** Four of the failures above surface a message pointing nowhere
near the cause unless verbose is on, because the packaging and Flutter
subprocess output is captured when `verbose < 1`.

## If you want to revisit

The realistic path is an **Android emulator** (`FLET_TEST_PLATFORM=android`),
where device mode is the supported configuration and full-app screenshots
work. That needs the Android SDK, which `flutter doctor` currently reports as
missing, and it tests the mobile build — which is parked (see
`PLAN-mobile.md`). Reconsider if mobile is ever unparked.

Until then, `tests/test_ledger_width.py` covers the ledger's width contract
structurally, and says plainly in its own docstring what that cannot prove.
