"""Tests for pure helpers extracted from theiaplayer.app.

These are the small, side-effect-free functions that fit between
UItight `app.py` and the heavy integration tests. They move
off-the-radar coverage from 0% to a meaningful baseline without
spinning up a full app.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from theiaplayer.app import VIEW_LABELS, TheIAPlayerApp
from theiaplayer.models import Playlist


def _bare_app():
    """Build an app with no real client — just enough to call _tracks_title."""
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app._playlists = []
    app._songs = []
    app._view_history = []
    return app


def test_tracks_title_returns_label_for_known_view():
    app = _bare_app()
    assert app._tracks_title("all-songs") == VIEW_LABELS["all-songs"]
    assert app._tracks_title("newest") == VIEW_LABELS["newest"]
    assert app._tracks_title("frequent") == VIEW_LABELS["frequent"]


def test_tracks_title_unknown_view_falls_back_to_tracks():
    app = _bare_app()
    assert app._tracks_title("nonexistent-view") == "tracks"


def test_tracks_title_playlist_uses_playlist_name():
    app = _bare_app()
    app._playlists = [
        Playlist(id="abc", name="Lectura", song_count=10),
        Playlist(id="xyz", name="Café", song_count=5),
    ]
    assert app._tracks_title("pl:abc") == "Lectura"
    assert app._tracks_title("pl:xyz") == "Café"


def test_tracks_title_unknown_playlist_falls_back_to_playlist():
    """A playlist id with no matching Playlist object yields the
    generic 'playlist' label."""
    app = _bare_app()
    app._playlists = [Playlist(id="abc", name="Lectura", song_count=10)]
    assert app._tracks_title("pl:ghost") == "playlist"


# ── _sidebar_highlighted event handler (pure routing) ────────────────


def test_sidebar_highlighted_ignores_folder_and_special_options():
    """Folder headers and the 'pl-new' option must not trigger a view
    change when the cursor brushes over them."""
    app = _bare_app()
    app._loading_playlists = False
    app.view = "all-songs"
    app._record_view_history = MagicMock()
    app._load_view = MagicMock()
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()

    # Folder header — should not load anything
    event = MagicMock()
    event.option = MagicMock()
    event.option.id = "folder:Lectura"
    app._sidebar_highlighted(event)
    app._load_view.assert_not_called()

    # pl-new — should not load anything
    event.option.id = "pl-new"
    app._sidebar_highlighted(event)
    app._load_view.assert_not_called()

    # no id — should not load anything
    event.option.id = None
    app._sidebar_highlighted(event)
    app._load_view.assert_not_called()


def test_sidebar_highlighted_records_history_on_real_change():
    app = _bare_app()
    app._loading_playlists = False
    app.view = "all-songs"
    app._record_view_history = MagicMock()
    app._load_view = MagicMock()
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()

    event = MagicMock()
    event.option = MagicMock()
    event.option.id = "newest"
    app._sidebar_highlighted(event)
    app._record_view_history.assert_called_once_with("all-songs")
    app._load_view.assert_called_once_with("newest")
    app.dirs.save_state.assert_called_once_with({"view": "newest"})


def test_sidebar_highlighted_same_view_does_not_reload_when_songs_loaded():
    """Highlighting the same view that's already showing WITH songs
    loaded is a no-op (avoids re-fetches when the cursor lingers)."""
    app = _bare_app()
    app._loading_playlists = False
    app.view = "newest"
    app._songs = [MagicMock()]  # any non-empty list
    app._record_view_history = MagicMock()
    app._load_view = MagicMock()
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()

    event = MagicMock()
    event.option = MagicMock()
    event.option.id = "newest"
    app._sidebar_highlighted(event)
    app._load_view.assert_not_called()


def test_sidebar_highlighted_same_view_does_reload_when_no_songs():
    """First arrival on a view (no songs loaded) forces a load even
    if the same view is highlighted."""
    app = _bare_app()
    app._loading_playlists = False
    app.view = "newest"
    app._songs = []
    app._record_view_history = MagicMock()
    app._load_view = MagicMock()
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()

    event = MagicMock()
    event.option = MagicMock()
    event.option.id = "newest"
    app._sidebar_highlighted(event)
    app._load_view.assert_called_once_with("newest")


def test_sidebar_highlighted_pin_prefix_unwraps_to_underlying_view():
    """A pinned favorite shows in the sidebar with id `pin:<view_id>`;
    the handler must unwrap and load the underlying view."""
    app = _bare_app()
    app._loading_playlists = False
    app.view = "all-songs"
    app._record_view_history = MagicMock()
    app._load_view = MagicMock()
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()

    event = MagicMock()
    event.option = MagicMock()
    event.option.id = "pin:frequent"
    app._sidebar_highlighted(event)
    app._load_view.assert_called_once_with("frequent")
    app.dirs.save_state.assert_called_once_with({"view": "frequent"})


def test_sidebar_highlighted_ignores_during_playlist_load():
    """``_loading_playlists`` flag suppresses the event to avoid
    programmatic highlights during the sidebar rebuild."""
    app = _bare_app()
    app._loading_playlists = True
    app.view = "all-songs"
    app._record_view_history = MagicMock()
    app._load_view = MagicMock()
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()

    event = MagicMock()
    event.option = MagicMock()
    event.option.id = "newest"
    app._sidebar_highlighted(event)
    app._load_view.assert_not_called()


# ── _record_view_history stack ───────────────────────────────────────


def test_record_view_history_appends_unique_consecutive_views():
    """The history stack deduplicates the immediately previous entry —
    adding "newest" twice in a row is a no-op."""
    app = _bare_app()
    app._record_view_history("all-songs")
    app._record_view_history("newest")
    app._record_view_history("newest")  # consecutive duplicate → ignored
    app._record_view_history("frequent")
    assert app._view_history == ["all-songs", "newest", "frequent"]


def test_record_view_history_appends_non_consecutive_duplicate():
    """A view that is not the immediately previous IS appended (the
    skip rule only blocks back-to-back duplicates)."""
    app = _bare_app()
    app._record_view_history("all-songs")
    app._record_view_history("newest")
    app._record_view_history("frequent")
    app._record_view_history("newest")  # non-consecutive → appended
    assert app._view_history == ["all-songs", "newest", "frequent", "newest"]


def test_record_view_history_caps_at_25_entries():
    """The history is bounded — once it hits 25, the oldest entry falls
    off so memory doesn't grow unbounded."""
    app = _bare_app()
    for i in range(30):
        app._record_view_history(f"view-{i}")
    assert len(app._view_history) == 25
    assert app._view_history[0] == "view-5"  # first 5 dropped
    assert app._view_history[-1] == "view-29"
