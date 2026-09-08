"""Proves the Flet 0.86 integration-test harness runs on this machine.

Deliberately does NOT touch the app: this test failing means the Flutter test
host is broken, not that Monarch Forecast is.

Run it with the command in ``tests/integration/README.md`` -- it needs the
platform, the app path and several ``--exclude`` entries, and is kept in one
place rather than duplicated here where the two copies would drift.
``flet test tests/integration`` does NOT work: the first positional argument
is the platform, so that form exits with ``invalid choice``.

Excluded from the default `pytest` sweep (see `addopts` in pyproject.toml)
because it needs a provisioned Flutter test host.
"""

import flet as ft
import pytest


async def _tiny_app(page: ft.Page):
    page.add(ft.Text("hello from flet testing"))


@pytest.mark.parametrize("flet_app", [{"flet_app_main": _tiny_app}], indirect=True)
async def test_harness_boots_and_finds_text(flet_app):
    await flet_app.tester.pump_and_settle()
    finder = await flet_app.tester.find_by_text("hello from flet testing")
    assert finder.count == 1
