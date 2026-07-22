"""Player configuration — player.toml alongside the server credentials file.

Parsed once at startup; never mutated at runtime (restart to apply changes).
Falls back to safe defaults if the file is absent or malformed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_KEYBINDS: dict = {
    "play_pause":           "space",
    "next_track":           "n",
    "prev_track":           "b",
    "search":               "slash",
    "shuffle":              "s",
    "repeat":               "r",
    "seek_back":            "left",
    "seek_fwd":             "right",
    "seek_back_big":        "shift+left",
    "seek_fwd_big":         "shift+right",
    "vol_down":             "minus",
    "vol_up":               "plus,equals_sign",
    "mute":                 "m",
    "enqueue":              "a",
    "enqueue_next":         "A",
    "queue_remove":         "x",
    "queue_clear":          "X",
    "queue_move_up":        "ctrl+up",
    "queue_move_down":      "ctrl+down",
    "star":                 "f",
    "share":                "S",
    "copy_text":            "c",
    "lyrics":               "L",
    "equalizer":            "ctrl+e,y",
    "go_to_album":          "e",
    "go_to_artist":         "E",
    "toggle_selection":     "v",
    "playlist_add":         "p",
    "notifications_toggle": "N",
    "panel_prev":           "h",
    "panel_next":           "l",
    "refresh":              "R",
    "theme_cycle":          "t",
    "theme_pick":           "T",
    "help":                 "question_mark",
    "quit":                 "q",
    "pin_toggle":           "i",
}

DEFAULT_FILTERS: dict = {
    "exclude_titles":   [],   # exclude songs whose title contains any string
    "exclude_artists":  [],   # exclude songs by these artists (exact)
    "exclude_genres":   [],   # exclude songs with these genres
    "min_duration":     0,    # 0 = disabled; exclude songs shorter than N seconds
    "max_duration":     0,    # 0 = disabled; exclude songs longer than N seconds
    "min_play_count":   0,    # 0 = disabled; exclude songs with fewer plays
}

DEFAULT_COLUMNS: dict = {
    "track_number": False,
    "artist":       True,
    "album":        False,
    "year":         False,
    "duration":     True,
    "bit_rate":     False,
    "genre":        False,
    "rating":       False,
    "play_count":   False,
}

DEFAULT_EQUALIZER: dict = {
    "enabled": False,
    "preset": "flat",
    "bands": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}

DEFAULTS: dict = {
    # playback
    "replaygain":           "album",   # track | album | no
    "gapless":              "yes",     # yes | no | weak
    "default_volume":       80,        # 0-130, -1 = restore last
    "replaygain_preamp":    0,         # preamp gain in dB (default: 0)
    "replaygain_fallback":  -6,        # fallback gain in dB if no metadata exists (default: -6)
    "equalizer":            DEFAULT_EQUALIZER,
    # integrations
    "desktop_notifications": True,
    "discord_rich_presence": False,
    "discord_app_id":       "",        # get one at discord.com/developers/applications
    "autoplay":             True,
    "audio_exclusive":      False,
    # sub-tables (merged separately below)
    "keybinds": DEFAULT_KEYBINDS,
    "filters":  DEFAULT_FILTERS,
    "columns":  DEFAULT_COLUMNS,
}

# ── loader ────────────────────────────────────────────────────────────────────

def _normalize_keybinds(overrides: dict) -> dict:
    """Normalize legacy nested keybinds from Go player (theia-subtui) to flat Python actions."""
    if "keybinds" not in overrides or not isinstance(overrides["keybinds"], dict):
        return overrides
    kb_data = overrides["keybinds"]
    has_subtables = any(isinstance(v, dict) for v in kb_data.values())
    if not has_subtables:
        return overrides
    MAPPING = {
        "play_pause": "play_pause",
        "next": "next_track",
        "prev": "prev_track",
        "shuffle": "shuffle",
        "loop": "repeat",
        "volume_up": "vol_up",
        "volume_down": "vol_down",
        "toggle_favorite": "star",
        "create_share_link": "share",
        "toggle_notifications": "notifications_toggle",
        "remove_from_queue": "queue_remove",
        "clear_queue": "queue_clear",
        "move_up": "queue_move_up",
        "move_down": "queue_move_down",
        "add_to_playlist": "playlist_add",
        "go_to_album": "go_to_album",
        "go_to_artist": "go_to_artist",
        "help": "help",
        "quit": "quit",
    }
    flat_keybinds = {**DEFAULT_KEYBINDS}
    for subtable_name, subtable in kb_data.items():
        if isinstance(subtable, dict):
            for go_action, keys in subtable.items():
                if go_action in MAPPING and isinstance(keys, list):
                    flat_keybinds[MAPPING[go_action]] = ",".join(keys)
    overrides["keybinds"] = flat_keybinds
    return overrides

def load(config_dir: Path) -> dict:
    """Return merged config: defaults + whatever player.toml overrides."""
    cfg: dict = {
        k: (dict(v) if isinstance(v, dict) else v)
        for k, v in DEFAULTS.items()
    }
    path = config_dir / "player.toml"
    if not path.exists():
        return cfg
    try:
        overrides = tomllib.loads(path.read_text())
        overrides = _normalize_keybinds(overrides)
        if "app" in overrides and isinstance(overrides["app"], dict):
            app_data = overrides.pop("app")
            for ak, av in app_data.items():
                if ak == "gapless_playback":
                    overrides["gapless"] = av
                else:
                    overrides[ak] = av
    except Exception:
        return cfg
    for k, v in overrides.items():
        if k not in DEFAULTS:
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = {**cfg[k], **{sk: sv for sk, sv in v.items() if sk in cfg[k]}}
        else:
            cfg[k] = v
    return cfg

def write_default(config_dir: Path) -> None:
    """Write a comprehensive commented player.toml on first run."""
    path = config_dir / "player.toml"
    if path.exists():
        return
    config_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# theia-player — player settings\n"
        "# Restart the app after editing.\n\n"

        "# ── Playback ─────────────────────────────────────────────────────────\n"
        '# replaygain = "album"   # track | album | no\n'
        '# gapless    = "yes"     # yes | no | weak\n'
        "# default_volume = 80    # 0-130, -1 = restore last session\n"
        "# replaygain_preamp = 0  # pre-amp gain in dB, positive or negative (default: 0)\n"
        "# replaygain_fallback = -6 # fallback gain in dB if no metadata exists (default: -6)\n\n"

        "# ── Integrations ─────────────────────────────────────────────────────\n"
        "# desktop_notifications = true\n"
        "# discord_rich_presence  = false\n"
        '# discord_app_id         = ""   # discord.com/developers/applications\n\n'

        "# ── Keybinds ─────────────────────────────────────────────────────────\n"
        "# [keybinds]\n"
        '# play_pause           = "space"\n'
        '# next_track           = "n"\n'
        '# prev_track           = "b"\n'
        '# search               = "slash"\n'
        '# shuffle              = "s"\n'
        '# repeat               = "r"\n'
        '# seek_back            = "left"\n'
        '# seek_fwd             = "right"\n'
        '# seek_back_big        = "shift+left"\n'
        '# seek_fwd_big         = "shift+right"\n'
        '# vol_down             = "minus"\n'
        '# vol_up               = "plus,equals_sign"\n'
        '# mute                 = "m"\n'
        '# enqueue              = "a"\n'
        '# enqueue_next         = "A"\n'
        '# queue_remove         = "x"\n'
        '# queue_clear          = "X"\n'
        '# queue_move_up        = "ctrl+up"\n'
        '# queue_move_down      = "ctrl+down"\n'
        '# star                 = "f"\n'
        '# share                = "S"\n'
        '# lyrics               = "L"\n'
        '# go_to_album          = "e"\n'
        '# go_to_artist         = "E"\n'
        '# toggle_selection     = "v"\n'
        '# playlist_add         = "p"\n'
        '# notifications_toggle = "N"\n'
        '# panel_prev           = "h"\n'
        '# panel_next           = "l"\n'
        '# refresh              = "R"\n'
        '# theme_cycle          = "t"\n'
        '# theme_pick           = "T"\n'
        '# help                 = "question_mark"\n'
        '# quit                 = "q"\n\n'

        "# ── Library Filters ───────────────────────────────────────────────────\n"
        "# [filters]\n"
        '# exclude_titles  = []   # exclude songs whose title contains any string\n'
        '# exclude_artists = []   # e.g. ["Various Artists"]\n'
        '# exclude_genres  = []   # e.g. ["Podcast", "Audiobook"]\n'
        "# min_duration    = 0    # seconds; 0 = disabled\n"
        "# max_duration    = 0    # seconds; 0 = disabled\n"
        "# min_play_count  = 0    # 0 = disabled\n\n"

        "# ── Columns ──────────────────────────────────────────────────────────\n"
        "# [columns]\n"
        "# track_number = false\n"
        "# artist       = true\n"
        "# album        = false\n"
        "# year         = false\n"
        "# duration     = true\n"
        "# bit_rate     = false\n"
        "# genre        = false\n"
        "# rating       = false\n"
        "# play_count   = false\n\n"

        "# ── Equalizer ────────────────────────────────────────────────────────\n"
        "# [equalizer]\n"
        "# enabled = false\n"
        '# preset = "flat"       # flat | bass | rock | pop | vocal | ...\n'
        "# bands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]\n"
    )

# ── filter ───────────────────────────────────────────────────────────────────

def filter_songs(songs: list, filters: dict) -> list:
    """Pure filter: apply the user-configured filter dict to a list of songs.

    Centralizes the filtering logic so the app instance method
    ``TheIAPlayerApp._apply_filters`` and the Auto DJ / autoplay path can
    share a single source of truth. Previously, Auto DJ was inlining
    ``playerconfig.apply_filters(songs, f)`` (which didn't exist as a
    function — leading to commit ``f8a9ee3``'s silent ``AttributeError``).
    """
    exclude_titles = [t.lower() for t in filters.get("exclude_titles", [])]
    exclude_artists = [a.lower() for a in filters.get("exclude_artists", [])]
    exclude_genres = [g.lower() for g in filters.get("exclude_genres", [])]
    min_dur = int(filters.get("min_duration", 0))
    max_dur = int(filters.get("max_duration", 0))
    min_plays = int(filters.get("min_play_count", 0))

    def keep(s) -> bool:
        if exclude_titles and any(t in s.title.lower() for t in exclude_titles):
            return False
        if exclude_artists and s.artist.lower() in exclude_artists:
            return False
        if exclude_genres and s.genre.lower() in exclude_genres:
            return False
        if min_dur and s.duration <= min_dur:
            return False
        if max_dur and s.duration >= max_dur:
            return False
        if min_plays and s.play_count < min_plays:
            return False
        return True

    return [s for s in songs if keep(s)]

# ── binding builder ───────────────────────────────────────────────────────────

def build_bindings(keybinds: dict):
    """Return a BINDINGS list for TheIAPlayerApp using the merged keybind map."""
    from textual.binding import Binding
    kb = {**DEFAULT_KEYBINDS, **keybinds}
    return [
        Binding(kb["play_pause"],           "play_pause",           "play/pause"),
        Binding(kb["next_track"],           "next_track",           "next"),
        Binding(kb["prev_track"],           "prev_track",           show=False),
        Binding(kb["search"],               "search",               "search"),
        Binding(kb["shuffle"],              "toggle_shuffle",       "shuffle"),
        Binding(kb["repeat"],               "cycle_repeat",         "repeat"),
        Binding(kb["seek_back"],            "seek(-5)",             show=False),
        Binding(kb["seek_fwd"],             "seek(5)",              show=False),
        Binding(kb["seek_back_big"],        "seek(-30)",            show=False),
        Binding(kb["seek_fwd_big"],         "seek(30)",             show=False),
        Binding(kb["vol_down"],             "volume(-5)",           show=False),
        Binding(kb["vol_up"],               "volume(5)",            show=False),
        Binding(kb["mute"],                 "mute",                 show=False),
        Binding(kb["enqueue"],              "enqueue(False)",       show=False),
        Binding(kb["enqueue_next"],         "enqueue(True)",        show=False),
        Binding(kb["queue_remove"],         "queue_remove",         show=False),
        Binding(kb["queue_clear"],          "queue_clear",          show=False),
        Binding(kb["queue_move_up"],        "queue_move(-1)",       show=False),
        Binding(kb["queue_move_down"],      "queue_move(1)",        show=False),
        Binding(kb["star"],                 "star",                 show=False),
        Binding(kb["share"],                "share",                show=False),
        Binding(kb["copy_text"],            "copy_text",            "copy info",            show=True),
        Binding(kb["lyrics"],               "show_lyrics",          show=False),
        Binding(kb["equalizer"],            "show_equalizer",       "eq",                   show=True),
        Binding(kb["go_to_album"],          "go_to_album",          show=False),
        Binding(kb["go_to_artist"],         "go_to_artist",         show=False),
        Binding(kb["toggle_selection"],     "toggle_selection",     show=False),
        Binding(kb["playlist_add"],         "playlist_add",         show=False),
        Binding(kb["notifications_toggle"], "toggle_notifications", "silent", show=True),
        Binding(kb["panel_prev"],           "focus_panel(-1)",      show=False),
        Binding(kb["panel_next"],           "focus_panel(1)",       show=False),
        Binding(kb["refresh"],              "refresh",              show=False),
        Binding(kb["theme_cycle"],          "cycle_kit_theme",      "theme"),
        Binding(kb["theme_pick"],           "change_theme",         show=False),
        Binding(kb["pin_toggle"],           "toggle_pin",           show=False),
        Binding(kb["help"],                 "help",                 "help"),
        Binding(kb["quit"],                 "quit",                 "quit"),
    ]
