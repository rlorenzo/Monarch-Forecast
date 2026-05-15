"""Design tokens for Monarch Forecast.

Single source of truth for the paper-and-ink palette and type roles defined
in DESIGN.md. Hex values are sRGB approximations of canonical OKLCH values;
DESIGN.md carries the OKLCH originals and is the file to consult when
deriving new tokens. Fonts are registered via ``page.fonts`` in
``src/main.py``; the names below match those registration keys.
"""

from __future__ import annotations

import flet as ft

# --- Brand --------------------------------------------------------------
# Coral is the brand mark. Used on <=10% of any screen at rest per the
# One Voice Rule in DESIGN.md.
CORAL = "#d97a64"
CORAL_DEEP = "#b8523f"  # hover / active state for coral surfaces
CORAL_TINT = "#fae3d8"  # light-mode emphasis fills

# --- Signal -------------------------------------------------------------
# Forecast meaning only. Never decorative. Each hue lives in a single role
# (positive = surplus, negative = shortfall, threshold = the safety line)
# per the Signal Separation Rule.
SIGNAL_POSITIVE = "#2e9764"
SIGNAL_NEGATIVE = "#d04632"
SIGNAL_THRESHOLD = "#d4a657"

# --- Light neutrals -----------------------------------------------------
# Tinted toward hue 30 at chroma 0.005-0.015. No untinted gray, no #fff.
PAPER = "#faf6f3"  # canonical surface
PAPER_2 = "#f4ece6"  # first tonal step (subtle layer)
PAPER_3 = "#ece1d8"  # emphasis fill (selected row, "today" band)
RULE = "#d6c5ba"  # borders, dividers, axes
INK = "#392b24"  # body text, headlines
INK_2 = "#5e4f47"  # secondary text
INK_3 = "#8c7c72"  # tertiary text (still WCAG AA on PAPER)

# --- Dark neutrals ------------------------------------------------------
# Same warm clay hue, dimmed. Not navy, not charcoal.
INK_DARK = "#22150f"  # canonical dark surface
INK_DARK_2 = "#2c1f17"  # first tonal step
INK_DARK_3 = "#3a2a22"  # emphasis fill
RULE_DARK = "#534138"  # borders in dark
PAPER_DARK = "#eadfd4"  # body text in dark
PAPER_DARK_2 = "#c4b0a3"  # secondary text in dark
PAPER_DARK_3 = "#907f73"  # tertiary text in dark

# --- Typography ---------------------------------------------------------
FONT_DISPLAY = "Fraunces"
FONT_BODY = "Inter"

# Variable-font sources from the google/fonts GitHub repo. They are fetched
# on first launch and cached by Flutter's HTTP cache for subsequent runs;
# offline support after first run is the result. A follow-up task can drop
# .ttf files into assets/fonts/ and switch these to local paths.
FONT_URLS: dict[str, str] = {
    FONT_DISPLAY: (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/"
        "Fraunces%5BSOFT%2CWONK%2Copsz%2Cwght%5D.ttf"
    ),
    FONT_BODY: (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"
    ),
}


# When the variable fonts above fail to fetch (offline first launch,
# upstream URL move), Flutter falls through to the next family that the
# platform can find. Keep these in sync with DESIGN.md's frontmatter
# typography fallbacks.
_DISPLAY_FALLBACK = ["Source Serif Pro", "Georgia", "serif"]
_BODY_FALLBACK = ["Helvetica Neue", "system-ui", "sans-serif"]

# Flet 0.84's TextStyle does not expose font-feature-settings, so we can't
# enable tabular lining figures at the style level. Inter's proportional
# figures are narrow enough that small ledgers still read cleanly; the
# Transactions tab is a follow-up where this matters more (see DESIGN.md
# "The Tabular Numerals Rule").


def display_style(color: str = INK) -> ft.TextStyle:
    """38pt Fraunces. Used once or twice per screen, never more."""
    return ft.TextStyle(
        font_family=FONT_DISPLAY,
        font_family_fallback=_DISPLAY_FALLBACK,
        size=38,
        weight=ft.FontWeight.W_500,
        letter_spacing=-0.4,
        height=1.05,
        color=color,
    )


def headline_style(color: str = INK) -> ft.TextStyle:
    """24pt Fraunces. Section titles and alert verdict lines."""
    return ft.TextStyle(
        font_family=FONT_DISPLAY,
        font_family_fallback=_DISPLAY_FALLBACK,
        size=24,
        weight=ft.FontWeight.W_500,
        letter_spacing=-0.12,
        height=1.15,
        color=color,
    )


def title_style(color: str = INK) -> ft.TextStyle:
    """16pt Inter 600. Sub-section titles, card headers, button labels."""
    return ft.TextStyle(
        font_family=FONT_BODY,
        font_family_fallback=_BODY_FALLBACK,
        size=16,
        weight=ft.FontWeight.W_600,
        height=1.3,
        color=color,
    )


def body_style(color: str = INK) -> ft.TextStyle:
    """13pt Inter 400. Default running text."""
    return ft.TextStyle(
        font_family=FONT_BODY,
        font_family_fallback=_BODY_FALLBACK,
        size=13,
        weight=ft.FontWeight.W_400,
        height=1.5,
        color=color,
    )


def label_style(color: str = INK_2) -> ft.TextStyle:
    """11pt Inter 500 UPPERCASE. Apply .upper() to the text content yourself.

    The 11pt floor (DESIGN.md) - never go smaller for visible text.
    """
    return ft.TextStyle(
        font_family=FONT_BODY,
        font_family_fallback=_BODY_FALLBACK,
        size=11,
        weight=ft.FontWeight.W_500,
        letter_spacing=0.66,
        height=1.4,
        color=color,
    )
