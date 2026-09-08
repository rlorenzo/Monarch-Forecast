"""Keep ``requirements.txt`` in step with ``pyproject.toml``.

``requirements.txt`` is a fallback for the CI build workflow (see README), so
it is hand-maintained rather than generated. That has already drifted twice —
a stale ``monarchmoneycommunity`` floor, then a stale ``flet`` pin left behind
by a version bump — and drift is invisible locally because ``uv sync`` reads
``pyproject.toml`` alone. These tests fail the moment the two disagree.
"""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_ROOT = Path(__file__).resolve().parent.parent


def _parse(lines: list[str], source: str) -> dict[str, Requirement]:
    """Map canonical name to requirement, rejecting duplicates.

    Keyed on the canonical name so ``flet-charts`` and ``flet_charts`` are the
    same package here as they are to an installer.

    Duplicates fail rather than overwrite. A dict comprehension keeps only the
    last of a repeated package, which is exactly the drift these tests exist to
    catch: a stale constraint left sitting above a fresh one would compare
    equal and pass, while pip resolves against both and can fail.
    """
    parsed: dict[str, Requirement] = {}
    for line in lines:
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        if name in parsed:
            pytest.fail(
                f"{source} lists {requirement.name} more than once: "
                f"'{parsed[name]}' and '{requirement}'"
            )
        parsed[name] = requirement
    return parsed


def _install_semantics(requirement: Requirement) -> tuple:
    """Everything an installer acts on, not just the version range.

    Extras, environment markers and direct-reference URLs all change what gets
    installed, so comparing ``.specifier`` alone would let the two manifests
    diverge into installing different things while still reporting agreement.
    """
    return (
        requirement.specifier,
        frozenset(requirement.extras),
        str(requirement.marker) if requirement.marker else None,
        requirement.url,
    )


def _pyproject_dependencies() -> dict[str, Requirement]:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return _parse(data["project"]["dependencies"], "pyproject.toml")


def _requirements_txt() -> dict[str, Requirement]:
    text = (_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [
        stripped
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    return _parse(lines, "requirements.txt")


def test_requirements_txt_covers_the_same_packages():
    assert _requirements_txt().keys() == _pyproject_dependencies().keys()


def test_requirements_txt_matches_pyproject_requirements():
    requirements = _requirements_txt()
    mismatched = {
        name: (str(dependency), str(requirements[name]))
        for name, dependency in _pyproject_dependencies().items()
        if name in requirements
        and _install_semantics(requirements[name]) != _install_semantics(dependency)
    }
    assert not mismatched, (
        f"requirements.txt disagrees with pyproject.toml (pyproject, requirements): {mismatched}"
    )
