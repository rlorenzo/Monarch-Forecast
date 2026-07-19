#!/usr/bin/env python3
"""Generate the DMG window background for Monarch Forecast.

Renders `dmg-background.png` (1x, 72 dpi) and `dmg-background@2x.png`
(2x, 144 dpi) next to this script. `sign_notarize.sh` combines them into a
HiDPI TIFF with `tiffutil -cathidpicheck`, so the installer window is crisp on
Retina displays.

Uses the app's real type — **Fraunces** (display serif) and **Inter** (body) —
the same variable fonts the app registers via `page.fonts` in
`src/views/tokens.py`. They're downloaded on demand into `.fonts-cache/`
(gitignored); if that fails (offline), it falls back to New York / SF so the
generator still runs.

The image only draws the framing (paper background, title, arrow, helper
text). The actual app icon and the Applications shortcut are overlaid by
`create-dmg` at the positions configured in `sign_notarize.sh`; keep the two in
sync (window 660x400, app icon centered at 170,200, Applications at 490,200).

Run:  uv run --with pillow python packaging/macos/make_dmg_background.py
"""

from __future__ import annotations

import pathlib
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / ".fonts-cache"

# Logical window size (points). Must match --window-size in sign_notarize.sh.
W, H = 660, 400
S = 2  # render at 2x, then downscale for the 1x file — crisp on both.

# Paper-and-ink palette (matches the app's design tokens).
PAPER = (250, 246, 239)
INK = (34, 31, 27)
MUTED = (140, 130, 116)
GREEN = (46, 125, 90)

# Icon centers (logical) — MUST match --icon / --app-drop-link positions.
APP_XY = (170, 200)
APPS_XY = (490, 200)

# The app's variable fonts (same sources as src/views/tokens.py::FONT_URLS).
FONT_URLS = {
    "Fraunces.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/"
        "Fraunces%5BSOFT%2CWONK%2Copsz%2Cwght%5D.ttf"
    ),
    "Inter.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"
    ),
}
# System-font fallbacks if the variable fonts can't be fetched.
FALLBACK_SERIF = "/System/Library/Fonts/NewYork.ttf"
FALLBACK_SANS = "/System/Library/Fonts/SFNS.ttf"


def _cached_font(name: str) -> pathlib.Path | None:
    dest = CACHE / name
    if dest.exists():
        return dest
    CACHE.mkdir(exist_ok=True)
    try:
        urllib.request.urlretrieve(FONT_URLS[name], dest)
        return dest
    except Exception as exc:  # offline / network error → fall back
        dest.unlink(missing_ok=True)  # drop any partial/corrupt download
        print(f"  ! could not fetch {name} ({exc}); using system fallback")
        return None


def _font(name: str, fallback: str, size: int, axes: dict[str, float]) -> ImageFont.FreeTypeFont:
    """Load a variable font at `size`, applying `axes` (matched by axis name).

    `axes` keys are matched case-insensitively against the font's axis names
    (e.g. "weight", "optical", "soft", "wonky"); missing axes keep their
    default so this works across Fraunces and Inter alike.
    """
    path = _cached_font(name)
    font = ImageFont.truetype(str(path) if path else fallback, size)
    try:
        wanted = []
        for ax in font.get_variation_axes():
            axname = ax["name"]
            axname = axname.decode() if isinstance(axname, bytes) else axname
            value = ax["default"]
            for key, val in axes.items():
                if key.lower() in axname.lower():
                    value = val
            wanted.append(value)
        if wanted:
            font.set_variation_by_axes(wanted)
    except Exception:
        pass  # static fallback font — nothing to vary
    return font


def _center_text(
    d: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    bbox = d.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    d.text((cx - width / 2, y), text, font=font, fill=fill)


def render() -> Image.Image:
    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)

    # Fraunces SemiBold at a large optical size — a substantial editorial
    # wordmark (not the thin default), wonk off for a clean install screen.
    title = _font(
        "Fraunces.ttf",
        FALLBACK_SERIF,
        30 * S,
        {"optical": 144, "weight": 600, "soft": 0, "wonky": 0},
    )
    body = _font("Inter.ttf", FALLBACK_SANS, 13 * S, {"weight": 440, "optical": 18})
    small = _font("Inter.ttf", FALLBACK_SANS, 11 * S, {"weight": 480, "optical": 14})

    # Title + instruction, top-centered.
    _center_text(d, (W // 2) * S, 38 * S, "Monarch Forecast", title, INK)
    _center_text(
        d,
        (W // 2) * S,
        86 * S,
        "Drag the app onto the Applications folder to install.",
        body,
        MUTED,
    )

    # Arrow from the app toward the Applications folder, at icon-center height.
    y = APP_XY[1] * S
    x1, x2 = 250 * S, 402 * S  # shaft
    tip = 416 * S  # arrowhead tip
    half = 11 * S  # arrowhead half-height
    d.line([(x1, y), (x2, y)], fill=GREEN, width=5 * S)
    d.ellipse([x1 - 2 * S, y - 2 * S, x1 + 2 * S, y + 2 * S], fill=GREEN)  # rounded tail
    d.polygon([(x2, y - half), (x2, y + half), (tip, y)], fill=GREEN)  # head

    # Footer tagline.
    _center_text(
        d, (W // 2) * S, 360 * S, "Financial forecasting powered by Monarch Money", small, MUTED
    )

    return img


def main() -> None:
    master = render()
    at2x = HERE / "dmg-background@2x.png"
    at1x = HERE / "dmg-background.png"
    # DPI tags matter: the 1x rep is 72 dpi (660x400 px = 660x400 pt) and the
    # 2x rep is 144 dpi (1320x800 px = the SAME 660x400 pt). sign_notarize.sh
    # combines them into a HiDPI TIFF with `tiffutil -cathidpicheck`, and this
    # tagging is what lets Finder render the 2x rep crisply on Retina instead
    # of scaling the 1x up (blurry).
    master.save(at2x, dpi=(144, 144))
    master.resize((W, H), Image.LANCZOS).save(at1x, dpi=(72, 72))
    print(f"wrote {at1x.name} ({W}x{H} @72dpi) and {at2x.name} ({W * S}x{H * S} @144dpi)")


if __name__ == "__main__":
    main()
