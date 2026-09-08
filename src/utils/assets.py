"""Where the app's bundled ``assets/`` directory lives.

Defined once because two modules need it from different depths in the source
tree: ``src/main.py`` hands the directory to ``ft.run(assets_dir=...)`` so the
``/fonts/...`` paths in ``tokens.FONT_ASSETS`` resolve, and
``src/views/dashboard.py`` reads the nav-rail seal out of it.

Resolved from ``__file__`` rather than the working directory, so it holds
wherever the app is launched from. It does *not* hold in packaged desktop
builds, where ``flet build`` lands the source somewhere else relative to the
assets it ships. Both call sites therefore check before trusting it and fall
back to the relative path that Flet's own bundled asset server resolves there.
"""

from __future__ import annotations

from pathlib import Path

# ``parents[2]`` from ``src/utils/assets.py`` is the project root.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
