"""Whitelist for vulture false positives.

Vulture can't see across runtime boundaries — frameworks that call into Python
by name (pytest fixtures, Flet event handlers) trigger unused-code warnings
on symbols that are actually used.

Add a new entry only after confirming the symbol is truly framework-dispatched,
not genuinely dead.
"""

# pytest fixtures are injected into test functions by parameter name.
tmp_session  # noqa: B018, F821  # pytest fixture in tests/test_session_manager.py
