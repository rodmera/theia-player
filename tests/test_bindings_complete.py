"""Verify that every entry in DEFAULT_KEYBINDS has a matching entry in
TheIAPlayerApp.BINDINGS, that build_bindings({}) produces them all, that
every binding action resolves to a real method on the app, and that no two
bindings claim the same key.

This is the regression net for the recurring pattern documented in the
project code review (2026-07-17): new DEFAULT_KEYBINDS keys get added
without a matching static ``Binding(...)`` entry, only to surface as bugs
one fix at a time. This suite turns that pattern into a CI failure.
"""

from __future__ import annotations

import pytest

from theiaplayer import config as playerconfig
from theiaplayer.app import TheIAPlayerApp


# Some DEFAULT_KEYBINDS entries are wired into TheIAPlayerApp.BINDINGS as
# parameterized actions (``seek(-5)``, ``volume(5)``, ``enqueue(False)``…)
# or under a renamed action (``shuffle`` -> ``toggle_shuffle``). Map each
# configurable key to the actual action string that lives in the static
# class BINDINGS so the test can compare apples to apples.
_ALIASES: dict[str, str] = {
    # parameterized
    "seek_back":            "seek(-5)",
    "seek_fwd":             "seek(5)",
    "seek_back_big":        "seek(-30)",
    "seek_fwd_big":         "seek(30)",
    "vol_down":             "volume(-5)",
    "vol_up":               "volume(5)",
    "enqueue":              "enqueue(False)",
    "enqueue_next":         "enqueue(True)",
    "queue_move_up":        "queue_move(-1)",
    "queue_move_down":      "queue_move(1)",
    "panel_prev":           "focus_panel(-1)",
    "panel_next":           "focus_panel(1)",
    # renamed for friendliness in the user-facing keybind map
    "shuffle":              "toggle_shuffle",
    "repeat":               "cycle_repeat",
    "lyrics":               "show_lyrics",
    "equalizer":            "show_equalizer",
    "notifications_toggle": "toggle_notifications",
    "theme_cycle":          "cycle_kit_theme",
    "theme_pick":           "change_theme",
    "pin_toggle":           "toggle_pin",
}


def _expected_actions() -> dict[str, str]:
    """Build {action_string: key_name} from DEFAULT_KEYBINDS."""
    keybinds: dict[str, str] = playerconfig.DEFAULT_KEYBINDS  # type: ignore[assignment]
    return {_ALIASES.get(k, k): k for k in keybinds}


def _binding_action_name(action: str) -> str:
    """Map a Binding.action to the Textual ``action_*`` method name.

    Textual strips the ``action_`` prefix off the App method when invoking,
    so a binding of ``"play_pause"`` resolves to ``self.action_play_pause``,
    and ``"seek(-5)"`` resolves to ``self.action_seek``.
    """
    base = action.split("(", 1)[0] if "(" in action else action
    return f"action_{base}"


# ── core: every configurable action must have a static binding ──────────────


def test_all_default_keybinds_have_static_class_binding():
    expected = set(_expected_actions())
    actual = {b.action for b in TheIAPlayerApp.BINDINGS if b.action is not None}
    missing = sorted(expected - actual)
    assert not missing, (
        "DEFAULT_KEYBINDS has no matching Binding.action in "
        f"TheIAPlayerApp.BINDINGS: {missing}. "
        "Add a Binding(...) entry in app.py BINDINGS = [...] for each."
    )


def test_build_bindings_returns_all_default_actions():
    expected = set(_expected_actions())
    actual = {b.action for b in playerconfig.build_bindings({}) if b.action is not None}
    missing = sorted(expected - actual)
    assert not missing, (
        f"build_bindings({{}}) is missing actions: {missing}. "
        "Add a Binding(...) entry in config.build_bindings()."
    )


# ── sanity: binding actions resolve to real methods on the app ──────────────


@pytest.mark.parametrize(
    "binding", TheIAPlayerApp.BINDINGS, ids=lambda b: b.action or b.key
)
def test_binding_action_resolves_to_app_method(binding):
    """Each ``Binding.action`` must map to a callable on TheIAPlayerApp.

    Prevents silent breakage when a method is renamed and the BINDINGS entry
    is forgotten.
    """
    method_name = _binding_action_name(binding.action)
    assert hasattr(TheIAPlayerApp, method_name), (
        f"Binding action '{binding.action}' references method "
        f"'{method_name}', which does not exist on TheIAPlayerApp."
    )
    assert callable(getattr(TheIAPlayerApp, method_name)), (
        f"Binding action '{binding.action}' references '{method_name}', "
        f"which exists but is not callable on TheIAPlayerApp."
    )


# ── sanity: no key string is claimed twice ───────────────────────────────────


def test_no_duplicate_keys_in_static_bindings():
    """Each key string must be bound to at most one action.

    Textual tolerates duplicates silently, but two bindings on the same key
    is almost always a copy-paste mistake.
    """
    keys: list[str] = []
    for b in TheIAPlayerApp.BINDINGS:
        keys.extend(k.strip() for k in b.key.split(","))
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"Duplicate key strings in TheIAPlayerApp.BINDINGS: {dupes}"


# ── sanity: parameterized aliases cover all referenced action families ──────


def test_aliases_only_reference_known_default_keybind_keys():
    """The _ALIASES map must point at keys that exist in DEFAULT_KEYBINDS."""
    unknown = sorted(set(_ALIASES) - set(playerconfig.DEFAULT_KEYBINDS))
    assert not unknown, (
        f"_ALIASES in this test references unknown DEFAULT_KEYBINDS keys: {unknown}. "
        f"Either add them to DEFAULT_KEYBINDS or remove them from _ALIASES."
    )