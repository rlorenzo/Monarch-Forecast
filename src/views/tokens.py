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
# Coral is the brand voice, used on <=10% of any screen at rest per the One
# Voice Rule in DESIGN.md. Plain CORAL is only 2.8:1 on PAPER, so it is
# reserved for decorative brand marks (logo seal, wordmark underscore).
# Anything that must be read or seen as a control (text, icons, the active
# rail, the chart line, filled buttons, focus outlines) uses CORAL_DEEP.
CORAL = "#d97a64"
CORAL_DEEP = "#a34431"  # 5.7:1 on PAPER, 4.9:1 on CORAL_TINT; filled-button fill
CORAL_INK = "#8a3727"  # filled-button hover/pressed; 7.4:1 under PAPER text
CORAL_TINT = "#fae3d8"  # light-mode emphasis fills

# --- Signal -------------------------------------------------------------
# Forecast meaning only. Never decorative. Each hue lives in a single role
# (positive = surplus, negative = shortfall, threshold = the safety line)
# per the Signal Separation Rule. Values are tuned so 12-13pt W600 amount
# text clears WCAG AA (>=4.5:1) on PAPER and PAPER_2 — amounts are small
# text, so the 3:1 large-text allowance does not apply.
SIGNAL_POSITIVE = "#217547"
SIGNAL_NEGATIVE = "#bd3a27"
SIGNAL_THRESHOLD = "#d4a657"  # the threshold line itself; 2.1:1, never text
SIGNAL_THRESHOLD_INK = "#8a6418"  # amber for icons/text that must read; 5.0:1 on PAPER

# --- Light neutrals -----------------------------------------------------
# Tinted toward hue 30 at chroma 0.005-0.015. No untinted gray, no #fff.
PAPER = "#faf6f3"  # canonical surface
PAPER_2 = "#f4ece6"  # first tonal step (subtle layer)
PAPER_3 = "#ece1d8"  # emphasis fill (selected row, "today" band)
RULE = "#d6c5ba"  # borders, dividers, axes
INK = "#392b24"  # body text, headlines
INK_2 = "#5e4f47"  # secondary text
INK_3 = "#77675d"  # tertiary text; 5.0:1 on PAPER, 4.6:1 on PAPER_2 (AA at 11pt)

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
FONT_DISPLAY = "Source Serif 4"
FONT_BODY = "Inter"

# Variable fonts, bundled under assets/fonts/ and served from the app's own
# asset directory. They used to be fetched from raw.githubusercontent.com on
# first launch, which meant a first run offline (or a GitHub outage, or a
# moved upstream path) silently fell through to the platform fallbacks below,
# and every launch made an outbound request before painting.
#
# Paths are asset-relative, which is what `assets_dir` in main.py's `ft.run`
# makes resolvable. Licences sit beside the files as required by the OFL.
FONT_ASSETS: dict[str, str] = {
    FONT_DISPLAY: "/fonts/SourceSerif4.ttf",
    FONT_BODY: "/fonts/Inter.ttf",
}


# If a bundled face above ever fails to register — a build that dropped
# assets/, a corrupt .ttf — Flutter falls through to the next family the
# platform can find. Much less likely now that the files ship with the app
# than when they were fetched over HTTP, but the app should still render
# readable text rather than tofu. Keep these in sync with DESIGN.md's
# frontmatter typography fallbacks.
_DISPLAY_FALLBACK = ["Georgia", "serif"]
_BODY_FALLBACK = ["Helvetica Neue", "system-ui", "sans-serif"]

# Flet's TextStyle does not expose font-feature-settings, so tabular lining
# figures can't be switched on. Money columns stay aligned by right-aligning
# them in fixed-width cells instead (see DESIGN.md "The Tabular Numerals
# Rule").


def display_style(color: str = INK) -> ft.TextStyle:
    """38pt Source Serif 4. Used once or twice per screen, never more.

    Reserved for editorial moments (the wordmark "Forecast", chapter
    titles) where the serif's character belongs. Never use this for
    numerical data — see ``figure_style`` for hero ledger figures.
    """
    return ft.TextStyle(
        font_family=FONT_DISPLAY,
        font_family_fallback=_DISPLAY_FALLBACK,
        size=38,
        weight=ft.FontWeight.W_500,
        letter_spacing=-0.4,
        height=1.05,
        color=color,
    )


def figure_style(color: str = INK) -> ft.TextStyle:
    """38pt Inter 700. The dashboard's hero numerical verdict.

    Inter (not the display serif) for big ledger figures: serif
    numerals flatter editorial copy but read literary at headline size,
    where a financial verdict needs calm authority. Bold weight + tight
    negative tracking give the figure decisive presence, and the minus
    glyph renders as a confident bar rather than a sliver. Pairs with
    Inter 600 used on the secondary ledger values (Starting/Net/Ending)
    so the two cards share a numerical voice.
    """
    return ft.TextStyle(
        font_family=FONT_BODY,
        font_family_fallback=_BODY_FALLBACK,
        size=38,
        weight=ft.FontWeight.W_700,
        letter_spacing=-0.8,
        height=1.05,
        color=color,
    )


def headline_style(color: str = INK) -> ft.TextStyle:
    """24pt Source Serif 4. Section titles and alert verdict lines."""
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


def figure_secondary_style(color: str = INK) -> ft.TextStyle:
    """24pt Inter 600. Secondary ledger figures (Starting / Net / Ending).

    Same numerical voice as ``figure_style`` one step down the scale, at the
    headline size so the type scale stays 38 / 24 / 16 / 13 / 11.
    """
    return ft.TextStyle(
        font_family=FONT_BODY,
        font_family_fallback=_BODY_FALLBACK,
        size=24,
        weight=ft.FontWeight.W_600,
        letter_spacing=-0.4,
        height=1.15,
        color=color,
    )


def button_style(color: str = PAPER) -> ft.TextStyle:
    """Button labels: the title role (16pt Inter 600), defaulting to PAPER
    for text on a filled CORAL_DEEP button. Pass INK for ghost buttons."""
    return title_style(color)


# Material shrinks a floating field label to 75% of its style size, so an
# 11pt label floats at ~8pt, under the floor. 11 / 0.75 lands it on 11pt.
_FLOATING_LABEL_SCALE = 0.75


def field_label_style(color: str = INK_2) -> ft.TextStyle:
    """Label role for TextField / Dropdown ``label_style``: 11pt once floated.

    Resting inside an empty field it shows at ~14.7pt, like a placeholder.
    """
    style = label_style(color)
    style.size = round(11 / _FLOATING_LABEL_SCALE, 2)
    style.letter_spacing = 0.88
    return style


def field_border(color: str = RULE, width: float = 1) -> dict[ft.ControlState, ft.InputBorder]:
    """Outline for TextField / Dropdown ``border``: hairline at rest, 2px
    CORAL_DEEP when focused."""
    return {
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(side=ft.BorderSide(width, color)),
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(side=ft.BorderSide(2, CORAL_DEEP)),
    }
