"""Tests for theiaplayer.config — particularly the Go-style keybind
normalizer (`_normalize_keybinds`) that converts a `theia-subtui`
nested TOML into the flat Python action names expected by
``build_bindings()``. This path is critical for users migrating from
the Go player and has zero coverage before this test file.
"""

from __future__ import annotations

import pytest
import textwrap

from theiaplayer import config as playerconfig
from theiaplayer.config import (
    DEFAULT_KEYBINDS,
    _normalize_keybinds,
    build_bindings,
    load,
    write_default,
)


# ── _normalize_keybinds ───────────────────────────────────────────────


def test_normalize_keybinds_passthrough_when_no_keybinds_section():
    """A config without a [keybinds] table is returned untouched."""
    overrides = {"replaygain": "track"}
    out = _normalize_keybinds(overrides)
    assert out is overrides or out == overrides
    assert out["replaygain"] == "track"


def test_normalize_keybinds_passthrough_when_already_flat():
    """A flat `[keybinds]` table (the legacy flat Python format) is
    returned unchanged."""
    overrides = {"keybinds": {"play_pause": "space", "next": "n"}}
    out = _normalize_keybinds(overrides)
    assert out["keybinds"] == {"play_pause": "space", "next": "n"}


def test_normalize_keybinds_translates_go_subtables():
    """The Go format groups keybinds by function. Each subtable maps Go
    action names to a list of keys; the normalizer must produce a flat
    dict keyed by Python action names with comma-joined keys."""
    overrides = {
        "keybinds": {
            "playback": {
                "play_pause": ["space"],
                "next": ["n"],
                "prev": ["b"],
                "shuffle": ["s"],
                "loop": ["r"],
                "volume_up": ["+"],
                "volume_down": ["-"],
            },
            "queue": {
                "add_to_playlist": ["p"],
                "remove_from_queue": ["x"],
                "clear_queue": ["X"],
                "move_up": ["ctrl+up"],
                "move_down": ["ctrl+down"],
            },
            "misc": {
                "toggle_favorite": ["f"],
                "create_share_link": ["S"],
                "toggle_notifications": ["N"],
                "go_to_album": ["e"],
                "go_to_artist": ["E"],
                "help": ["?"],
                "quit": ["q"],
            },
        }
    }
    out = _normalize_keybinds(overrides)
    kb = out["keybinds"]
    assert kb["play_pause"] == "space"
    assert kb["next_track"] == "n"
    assert kb["prev_track"] == "b"
    assert kb["shuffle"] == "s"
    assert kb["repeat"] == "r"
    assert kb["vol_up"] == "+"
    assert kb["vol_down"] == "-"
    assert kb["playlist_add"] == "p"
    assert kb["queue_remove"] == "x"
    assert kb["queue_clear"] == "X"
    assert kb["queue_move_up"] == "ctrl+up"
    assert kb["queue_move_down"] == "ctrl+down"
    assert kb["star"] == "f"
    assert kb["share"] == "S"
    assert kb["notifications_toggle"] == "N"
    assert kb["go_to_album"] == "e"
    assert kb["go_to_artist"] == "E"
    assert kb["help"] == "?"
    assert kb["quit"] == "q"


def test_normalize_keybinds_joins_multiple_keys():
    """A Go-style action can list multiple keys; the normalizer joins
    them with commas so the result fits the binding parser."""
    overrides = {
        "keybinds": {
            "misc": {
                "play_pause": ["space", "k"],
            }
        }
    }
    out = _normalize_keybinds(overrides)
    assert out["keybinds"]["play_pause"] == "space,k"


def test_normalize_keybinds_ignores_unknown_go_actions():
    """An unknown Go action in the subtable is silently dropped (the
    migration is best-effort — missing mappings are filled from
    DEFAULT_KEYBINDS, not rejected)."""
    overrides = {
        "keybinds": {
            "misc": {
                "play_pause": ["space"],
                "banana_peel": ["z"],  # not in the mapping
            }
        }
    }
    out = _normalize_keybinds(overrides)
    assert out["keybinds"]["play_pause"] == "space"
    assert "banana_peel" not in out["keybinds"]


def test_normalize_keybinds_invalid_keys_value_is_ignored():
    """If a Go action's value is not a list (e.g. a string), the normalizer
    silently drops it rather than raising — the key still keeps the
    default fallback."""
    overrides = {
        "keybinds": {
            "misc": {
                "play_pause": ["space"],
                "next": "not a list",  # malformed → not overridden
            }
        }
    }
    out = _normalize_keybinds(overrides)
    assert out["keybinds"]["play_pause"] == "space"
    # next_track is the default (the malformed override was dropped)
    assert out["keybinds"]["next_track"] == DEFAULT_KEYBINDS["next_track"]


def test_normalize_keybinds_empty_list_should_keep_default():
    """Regression: an empty list value currently produces an empty
    string binding key, which silently creates a useless binding.
    The expected behavior is to fall back to the default — the user
    can remove the action by other means (e.g. unset in the flat
    namespace). Until this is fixed, the test pins the current
    behavior so the bug is visible."""
    overrides = {
        "keybinds": {
            "misc": {
                "play_pause": [],  # explicit empty
            }
        }
    }
    out = _normalize_keybinds(overrides)
    # Today: empty string "" (bug → useless binding)
    # Expected: DEFAULT_KEYBINDS["play_pause"] ("space")
    if out["keybinds"]["play_pause"] == "":
        # Pin the bug so a fix is required to change this assertion.
        pytest.fail(
            "BUG: empty list override creates a binding with empty key. "
            "Should keep the default fallback. Will silently disable the "
            "binding instead of reverting to the default key."
        )
    assert out["keybinds"]["play_pause"] == DEFAULT_KEYBINDS["play_pause"]


def test_normalize_keybinds_preserves_defaults_for_missing_actions():
    """The normalizer starts from DEFAULT_KEYBINDS so unmapped actions
    keep their original binding (the user only overrides what they care
    about)."""
    assert DEFAULT_KEYBINDS["play_pause"] == "space"
    overrides = {
        "keybinds": {
            "misc": {
                "next": ["m"],  # remap next
            }
        }
    }
    out = _normalize_keybinds(overrides)
    # play_pause defaulted since the user didn't override it
    assert out["keybinds"]["play_pause"] == DEFAULT_KEYBINDS["play_pause"]
    # next overrides
    assert out["keybinds"]["next_track"] == "m"


def test_normalize_keybinds_handles_non_dict_subtable_safely():
    """If a subtable isn't a dict (e.g. a string), the normalizer must
    not crash — that whole subtable is just ignored."""
    overrides = {
        "keybinds": {
            "misc": "not a dict",
            "playback": {
                "play_pause": ["space"],
            },
        }
    }
    out = _normalize_keybinds(overrides)
    assert out["keybinds"]["play_pause"] == "space"


# ── load + write_default ───────────────────────────────────────────────


def test_load_returns_defaults_when_no_file(tmp_path):
    """First run with no player.toml: defaults only, no exception."""
    cfg = load(tmp_path)
    assert cfg["replaygain"] == "album"
    assert cfg["gapless"] == "yes"
    assert cfg["default_volume"] == 80
    assert cfg["keybinds"] == DEFAULT_KEYBINDS


def test_load_applies_overrides_from_file(tmp_path):
    toml = tmp_path / "player.toml"
    toml.write_text(textwrap.dedent("""
        replaygain = "track"
        gapless = "no"
        default_volume = 60
    """))
    cfg = load(tmp_path)
    assert cfg["replaygain"] == "track"
    assert cfg["gapless"] == "no"
    assert cfg["default_volume"] == 60


def test_load_inherits_defaults_for_missing_keys(tmp_path):
    """A partial player.toml only overrides the listed keys; the rest
    comes from DEFAULTS."""
    toml = tmp_path / "player.toml"
    toml.write_text('default_volume = 100\n')
    cfg = load(tmp_path)
    assert cfg["default_volume"] == 100
    assert cfg["replaygain"] == "album"  # default


def test_load_app_gapless_alias_remap(tmp_path):
    """The Go player named the option `gapless_playback`; the loader
    accepts that alias and remaps it to `gapless`."""
    toml = tmp_path / "player.toml"
    toml.write_text(textwrap.dedent("""
        [app]
        gapless_playback = "weak"
    """))
    cfg = load(tmp_path)
    assert cfg["gapless"] == "weak"


def test_load_app_other_keys_pass_through(tmp_path):
    """Keys under [app] other than the alias bubble up to the top level."""
    toml = tmp_path / "player.toml"
    toml.write_text(textwrap.dedent("""
        [app]
        desktop_notifications = false
    """))
    cfg = load(tmp_path)
    assert cfg["desktop_notifications"] is False


def test_load_unknown_keys_are_ignored(tmp_path):
    """Keys not in DEFAULTS are silently dropped (forward compat)."""
    toml = tmp_path / "player.toml"
    toml.write_text('made_up_key = "x"\n')
    cfg = load(tmp_path)
    assert "made_up_key" not in cfg


def test_load_corrupt_file_returns_defaults(tmp_path):
    """A malformed TOML must not crash the app — fall back to defaults."""
    toml = tmp_path / "player.toml"
    toml.write_text("this is not valid toml = = =}}")
    cfg = load(tmp_path)
    assert cfg["replaygain"] == "album"  # defaults intact


def test_load_filters_dict_merge_underscore(tmp_path):
    """Custom filters under [filters] extend the default dict but only
    for known keys (no forward-compat pollution)."""
    toml = tmp_path / "player.toml"
    toml.write_text(textwrap.dedent("""
        [filters]
        exclude_genres = ["podcast"]
        custom_unknown = "ignored"
    """))
    cfg = load(tmp_path)
    assert "podcast" in cfg["filters"]["exclude_genres"]
    assert "custom_unknown" not in cfg["filters"]


def test_load_keybinds_go_style_normalized(tmp_path):
    """End-to-end: a Go-style player.toml is normalized end-to-end."""
    toml = tmp_path / "player.toml"
    toml.write_text(textwrap.dedent("""
        [keybinds.playback]
        play_pause = ["space"]
        next = ["n"]
    """))
    cfg = load(tmp_path)
    assert cfg["keybinds"]["play_pause"] == "space"
    assert cfg["keybinds"]["next_track"] == "n"


def test_write_default_skips_when_file_exists(tmp_path):
    """``write_default`` is a no-op if player.toml already exists (the
    user has customized it)."""
    target = tmp_path / "player.toml"
    target.write_text("my custom settings\n")
    write_default(tmp_path)
    assert target.read_text() == "my custom settings\n"


def test_write_default_creates_commented_sample(tmp_path):
    """First run: write_default creates a fully commented player.toml."""
    write_default(tmp_path)
    out = (tmp_path / "player.toml").read_text()
    assert "theia-player" in out
    # Has all major sections as comments
    assert "replaygain" in out
    assert "gapless" in out
    assert "default_volume" in out
    assert "desktop_notifications" in out
    assert "discord_rich_presence" in out
    assert "keybinds" in out


def test_write_default_creates_parent_dir(tmp_path):
    """The loader's dir might not exist yet — write_default must create it."""
    target = tmp_path / "subdir" / "player.toml"
    write_default(tmp_path / "subdir")
    assert target.exists()


# ── build_bindings ─────────────────────────────────────────────────────


def test_build_bindings_empty_returns_all_defaults():
    """No overrides → every default keybind action becomes a binding."""
    bindings = build_bindings({})
    actions = {b.action for b in bindings if b.action}
    assert "play_pause" in actions
    assert "next_track" in actions
    assert "prev_track" in actions


def test_build_bindings_override_changes_key():
    """Overriding the play_pause key overrides the binding key, not the
    action — the action stays the same but the key string changes."""
    bindings = build_bindings({"play_pause": "k"})
    pp = next(b for b in bindings if b.action == "play_pause")
    # `key` may be a single string or a tuple; normalize both
    keys = pp.key.split(",") if isinstance(pp.key, str) else pp.key
    assert "k" in keys


def test_build_bindings_unknown_action_ignored():
    """Unknown actions in the override dict are silently ignored (the
    action has no static binding anyway)."""
    bindings = build_bindings({"play_pause": "space", "nonsense": "z"})
    actions = {b.action for b in bindings if b.action}
    assert "play_pause" in actions
    assert "nonsense" not in actions


def test_build_bindings_uses_subtui_aliases():
    """Keys named with Go-subtui aliases (e.g. ``vol_up``) are routed to
    the parameterized Python action (``volume(5)``)."""
    bindings = build_bindings({"vol_up": "=", "vol_down": "-"})
    # both should map to ``volume`` with a sign arg
    actions = {b.action for b in bindings if b.action}
    assert "volume(5)" in actions
    assert "volume(-5)" in actions
