"""Unit tests for theiaplayer.terminal_probe.

Verifies the centralized TTY/ANSI detection logic that replaced the
scattered monkey-patches that used to live in art.py and app.main().
"""

from __future__ import annotations

import importlib
import os

import pytest

from theiaplayer import terminal_probe


@pytest.fixture
def fresh_probe(monkeypatch):
    """Yield a terminal_probe module with its probe() reset so each test starts clean."""
    monkeypatch.setattr(terminal_probe, "_PROBED", False)
    yield terminal_probe


def test_is_kitty_compatible_detects_ghostty(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("TERM", raising=False)
    assert terminal_probe.is_kitty_compatible() is True


def test_is_kitty_compatible_detects_kitty(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "kitty")
    monkeypatch.delenv("TERM", raising=False)
    assert terminal_probe.is_kitty_compatible() is True


def test_is_kitty_compatible_detects_kitty_via_term(monkeypatch):
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("TERM", "xterm-kitty")
    assert terminal_probe.is_kitty_compatible() is True


def test_is_kitty_compatible_false_for_other_terminals(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert terminal_probe.is_kitty_compatible() is False


def test_force_protocol_sets_tgp_on_ghostty(fresh_probe, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("NAVITUI_ART", raising=False)
    fresh_probe._force_protocol_for_terminal()
    assert os.environ.get("NAVITUI_ART") == "tgp"


def test_force_protocol_does_not_override_user_choice(fresh_probe, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setenv("NAVITUI_ART", "sixel")
    fresh_probe._force_protocol_for_terminal()
    assert os.environ.get("NAVITUI_ART") == "sixel"


def test_force_protocol_skipped_on_other_terminals(fresh_probe, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.delenv("NAVITUI_ART", raising=False)
    fresh_probe._force_protocol_for_terminal()
    assert os.environ.get("NAVITUI_ART") is None


def test_current_protocol_returns_env_var(fresh_probe, monkeypatch):
    monkeypatch.setenv("NAVITUI_ART", "halfcell")
    assert fresh_probe.current_protocol() == "halfcell"


def test_current_protocol_defaults_to_auto(fresh_probe, monkeypatch):
    monkeypatch.delenv("NAVITUI_ART", raising=False)
    assert fresh_probe.current_protocol() == "auto"


def test_probe_is_idempotent(fresh_probe, monkeypatch):
    """Calling probe() twice does not double-apply the patches."""
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("NAVITUI_ART", raising=False)
    fresh_probe.probe()
    assert os.environ.get("NAVITUI_ART") == "tgp"
    # Force NAVITUI_ART to a sentinel; a second probe() must NOT overwrite it.
    monkeypatch.setenv("NAVITUI_ART", "unicode")
    fresh_probe.probe()
    assert os.environ.get("NAVITUI_ART") == "unicode"


def test_probe_does_not_override_explicit_navitudi_art(fresh_probe, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setenv("NAVITUI_ART", "off")
    fresh_probe.probe()
    assert os.environ.get("NAVITUI_ART") == "off"


def test_module_import_auto_runs_probe():
    """Importing terminal_probe must run probe() automatically.

    We reimport under a fresh subprocess-like isolation by checking the
    module's _PROBED flag is True after import.
    """
    importlib.reload(terminal_probe)
    try:
        assert terminal_probe._PROBED is True
    finally:
        # Reset so other tests start clean again.
        terminal_probe._PROBED = False