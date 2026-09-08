"""The packaged app builds, launches and renders without crashing.

This is the one thing `flet.testing` *can* do for a macOS desktop app (see
README.md for everything it cannot). No finders, no screenshots — booting the
real packaged bundle and pumping frames without an exception is the assertion.

That is not nothing. It exercises the whole packaging path the unit suite never
touches: the Flutter build, the embedded Python runtime, and packaging the
assets into the `.app`.

Be clear about the limit, though: this asserts the app does not *crash*, not
that it renders correctly. A missing bundled font falls back to the platform
faces silently, and this test still passes. Confirming the fonts actually load
from file means running with `-v` and reading the Flutter log for
`Font loaded from file:` — see README.md. `tests/test_main_entry.py` covers the
static half, that `assets_dir` is passed and the files it names exist.

Excluded from the default `pytest` sweep; run it with the command in README.md.
"""

import flet as ft
import pytest


@pytest.mark.parametrize("flet_app", [{"skip_pump_and_settle": True}], indirect=True)
async def test_app_boots_and_renders(flet_app):
    """Pump rather than settle: the login screen's indeterminate ProgressBar
    means `pump_and_settle` never reaches a quiet frame (README.md)."""
    for _ in range(6):
        await flet_app.tester.pump(ft.Duration(milliseconds=500))
